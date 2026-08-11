"""网页正文抓取：开放搜索第三级证据用。

轻量实现（不引 bs4/lxml 新依赖）：httpx 拉取 -> 去 script/style -> 去标签 ->
按 claim 关键词定位正文窗口。失败返回 None，由调用方降级（政府站用 snippet，其他跳过）。
"""
import asyncio
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx

from app.core.logging import get_logger

logger = get_logger(__name__)

_MAX_CHARS = 4000
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_REDIRECTS = 3
_REDIRECT_STATUS = {301, 302, 303, 307, 308}
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
_SCRIPT_STYLE_RE = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>", re.S | re.I)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_META_CHARSET_RE = re.compile(br"<meta[^>]+charset=[\"']?([A-Za-z0-9_-]+)", re.I)
_WS_RE = re.compile(r"[ \t ​]+")
_BLANK_LINES_RE = re.compile(r"\n{2,}")
# 正文密度启发：优先取含中文标点多的大块
_BLOCK_SPLIT_RE = re.compile(r"\n")


def _decode_html(body: bytes, response_encoding: str | None) -> str:
    """优先尊重 HTML 的 meta charset，避免 gb2312 页面被 UTF-8 解成乱码。"""
    declared = _META_CHARSET_RE.search(body[:4096])
    encoding = declared.group(1).decode("ascii", errors="ignore").lower() if declared else ""
    aliases = {"gb2312": "gb18030", "gbk": "gb18030", "gb18030": "gb18030", "utf-8": "utf-8"}
    chosen = aliases.get(encoding, response_encoding or "utf-8")
    try:
        return body.decode(chosen, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


async def _is_public_url(url: str) -> bool:
    """抓取前和每次重定向后验证地址，拒绝本机、私网和非 HTTP(S) 目标。"""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        host = parsed.hostname.rstrip(".").lower()
        if host == "localhost" or host.endswith((".localhost", ".local")):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            pass

        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        )
        addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
        return bool(addresses) and all(address.is_global for address in addresses)
    except (OSError, ValueError):
        return False


def _html_to_text(html: str) -> str:
    text = _SCRIPT_STYLE_RE.sub("\n", html)
    text = _COMMENT_RE.sub("", text)
    # 块级标签换成换行，保住段落结构
    text = re.sub(r"<(p|div|br|h[1-6]|li|tr|section|article)[^>]*>", "\n", text, flags=re.I)
    text = _TAG_RE.sub("", text)
    # HTML 实体（只处理常见的，避免引 html 库做全量反转义）
    for ent, ch in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                    ("&quot;", '"'), ("&#39;", "'"), ("&ldquo;", "“"), ("&rdquo;", "”")):
        text = text.replace(ent, ch)
    lines = [ln for ln in (_WS_RE.sub("", ln) for ln in text.split("\n")) if len(ln) >= 8]
    return _BLANK_LINES_RE.sub("\n", "\n".join(lines))


# claim 中的区分性 token：数字+单位（4000万个/2030年/1.1亿辆）与书名号专名
# 这些才是"证据句子"的定位锚点；通用词（规划/提出/电网）全文都是，没有定位价值
_DISTINCTIVE_RE = re.compile(
    r"[\d.]+\s*(?:万个|万辆|亿|万|%|年|月|日|个|辆|千瓦|元|人次|例)|《[^》]{2,30}》"
)


def _window_around(text: str, needle: str) -> str:
    """分块打分取 Top-2 窗口拼接：区分性 token（数字/专名）权重 ×3，通用 2-gram 权重 ×1。

    内嵌坑：单窗口按全 claim 2-gram 打分会被通用词带偏——claim 里"规划/提出"
    满文都是，真正关键的"4000万个"只有 4 个弱 gram，窗口会错过证据句。
    """
    if len(text) <= _MAX_CHARS:
        return text
    distinctive = _DISTINCTIVE_RE.findall(needle)
    grams = [needle[i : i + 2] for i in range(max(len(needle) - 1, 1))]
    chunk_size, overlap = 2000, 200
    chunks: list[tuple[int, str]] = []  # (score, chunk)
    pos = 0
    while pos < len(text):
        seg = text[pos : pos + chunk_size]
        score = sum(seg.count(g) for g in grams) + 3 * sum(
            seg.count(tok) for tok in distinctive
        )
        chunks.append((score, seg))
        pos += chunk_size - overlap
    chunks.sort(key=lambda c: c[0], reverse=True)
    top = [c[1] for c in chunks[:2] if c[0] > 0]
    if not top:
        return text[:_MAX_CHARS]
    # 按原文顺序拼接，去掉重复块
    ordered = sorted(top, key=lambda c: text.find(c[:80]))
    out: list[str] = []
    for c in ordered:
        if not any(c[:200] in o for o in out):
            out.append(c)
    return "\n……\n".join(out)[:_MAX_CHARS]


async def fetch_page_text(url: str, claim: str = "", timeout: float = 8.0) -> str | None:
    """抓取网页并提取正文文本；失败/内容过短返回 None。"""
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"},
        ) as client:
            current_url = url
            for _ in range(_MAX_REDIRECTS + 1):
                if not await _is_public_url(current_url):
                    logger.info("page fetch blocked unsafe url=%s", current_url[:80])
                    return None
                async with client.stream("GET", current_url) as resp:
                    if resp.status_code in _REDIRECT_STATUS:
                        location = resp.headers.get("location")
                        if not location:
                            return None
                        current_url = urljoin(current_url, location)
                        continue
                    if resp.status_code != 200:
                        logger.info("page fetch http %d url=%s", resp.status_code, current_url[:80])
                        return None
                    content_type = resp.headers.get("content-type", "")
                    if "text" not in content_type and "html" not in content_type:
                        return None
                    content_length = resp.headers.get("content-length")
                    if content_length and int(content_length) > _MAX_RESPONSE_BYTES:
                        logger.info("page fetch too large url=%s", current_url[:80])
                        return None
                    body = bytearray()
                    async for chunk in resp.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_RESPONSE_BYTES:
                            logger.info("page fetch exceeded limit url=%s", current_url[:80])
                            return None
                    html = _decode_html(bytes(body), resp.encoding)
                    break
            else:
                logger.info("page fetch too many redirects url=%s", url[:80])
                return None
    except (httpx.HTTPError, ValueError) as exc:
        logger.info("page fetch failed url=%s err=%s", url[:80], type(exc).__name__)
        return None
    text = _html_to_text(html)
    if len(text) < 100:
        return None
    return _window_around(text, claim) if claim else text[:_MAX_CHARS]
