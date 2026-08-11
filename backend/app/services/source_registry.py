"""来源注册表服务：加载 source_registry.yaml，域名白名单 + 权威分级 + 转载作者匹配。

SPEC 11 内嵌坑：指定站无站内搜索 API -> 搜索引擎 + 程序白名单校验，
防止搜索引擎返回结果越界。

权威三级筛选（v2 新增）：
1. authority_of(url)：注册表域名精确匹配 / .gov.cn 泛匹配 -> (tier, name)
2. match_author_alias(text)：转载来源别名匹配（"新华社电""来源：人民网"）-> (tier, name)
3. 都不中 -> 由编排层抓正文交 authority-v1 模型兜底
"""
import re
from functools import lru_cache
from urllib.parse import urlparse

import yaml

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# 档位排序：越小越权威（gov_original 单条可定论，provincial/local 需两条独立来源）
TIER_RANK = {
    "gov_original": 0,
    "national_media": 1,
    "provincial_media": 2,
    "local_official": 3,
}

# 转载来源提示模式（候选串只负责"圈范围"，最终靠别名索引 substring 校验）：
# "来源：XX" / "据XX报道" / "本文转自【XX】" / "XX北京8月6日电"（通讯社电头）
_HINT_RES = [
    re.compile(r"(?:来源|信息来源|出处)[：:]\s*([一-龥A-Za-z0-9·]{2,20})"),
    re.compile(r"据([一-龥A-Za-z0-9·]{2,15}?)(?:报道|消息|介绍|获悉)"),
    re.compile(r"(?:本文)?转自[【\[]?([一-龥A-Za-z0-9·]{2,20})"),
    re.compile(r"([一-龥]{2,12})(?:\d{1,2}月\d{1,2}日)?电"),
]


class SourceRegistry:
    def __init__(self, data: dict) -> None:
        self._designated: list[dict] = data.get("designated_sites", [])
        self._dedupe_groups: list[list[str]] = data.get("dedupe_groups", [])
        self._qualified_patterns: list[dict] = data.get("qualified_open_web_patterns", [])
        self._blocked: list[str] = data.get("blocked_domains", [])
        self._authority: list[dict] = data.get("authority_sources", [])
        # 别名 -> (tier, name) 索引；别名统一去空格便于匹配
        self._alias_index: dict[str, tuple[str, str, tuple[str, ...]]] = {}
        for src in self._authority:
            for alias in src.get("aliases", []):
                key = alias.replace(" ", "")
                if key and (key not in self._alias_index
                            or TIER_RANK.get(src["tier"], 9) < TIER_RANK.get(self._alias_index[key][0], 9)):
                    self._alias_index[key] = (
                        src["tier"], src["name"], tuple(src.get("use_for", []))
                    )

    @staticmethod
    def _domain_value(domain) -> str | None:
        if domain is None:
            return None
        return getattr(domain, "value", domain)

    def _supports_domain(self, item: dict, domain) -> bool:
        value = self._domain_value(domain)
        allowed = item.get("use_for", [])
        return value is None or not allowed or value in allowed

    # ── 指定站（第二级证据链）──
    @property
    def designated_domains(self) -> list[str]:
        return [s["domain"] for s in self._designated]

    def designated_domains_for(self, domain) -> list[str]:
        return [s["domain"] for s in self._designated if self._supports_domain(s, domain)]

    def publisher_of(self, url: str) -> str:
        host = (urlparse(url).hostname or "").lower()
        for site in self._designated:
            if host == site["domain"] or host.endswith("." + site["domain"]):
                return site["publisher"]
        return ""

    def is_designated(self, url: str) -> bool:
        return self.is_designated_for(url, None)

    def is_designated_for(self, url: str, domain) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path or "/"
        for site in self._designated:
            if not self._supports_domain(site, domain):
                continue
            if host != site["domain"] and not host.endswith("." + site["domain"]):
                continue
            paths = site.get("paths", [])
            if not paths or any(p == "/" or path.startswith(p) for p in paths):
                return True
        return False

    def is_blocked(self, url: str) -> bool:
        lowered = url.lower()
        host = (urlparse(url).hostname or "").lower()
        return any(host == b or host.endswith("." + b) or b in lowered for b in self._blocked)

    # ── 权威分级（第三级开放搜索）──
    def authority_of(self, url: str, domain=None) -> tuple[str, str] | None:
        """第一级：域名精确匹配 -> (tier, 来源名)。blocked 返回 None 由调用方先拦。"""
        host = (urlparse(url).hostname or "").lower()
        if not host:
            return None
        best: tuple[str, str] | None = None
        registered_host = False
        for src in self._authority:
            for d in src.get("domains", []):
                d = d.lower()
                if host == d or host.endswith("." + d):
                    registered_host = True
                    if not self._supports_domain(src, domain):
                        continue
                    cand = (src["tier"], src["name"])
                    if best is None or TIER_RANK.get(cand[0], 9) < TIER_RANK.get(best[0], 9):
                        best = cand
        if best:
            return best
        if registered_host:
            return None
        # 后缀泛匹配兜底（*.gov.cn -> gov_original，覆盖未单列的部委/地方政府）
        for p in self._qualified_patterns:
            if host.endswith(p["suffix"]):
                return (p["tier"], host)
        return None

    def match_author_alias(
        self, text: str, domain=None, *, attribution_only: bool = False
    ) -> tuple[str, str] | None:
        """第二级：转载作者匹配。返回 (tier, 原始发布主体名)；多个命中取最高档。

        两遍扫描：
        1. 提示模式圈候选串（来源：XX / 据XX报道 / 转自XX / XX电），候选串里查别名
        2. 全文安全别名直接扫描（len>=3 的别名，如"新华社""国家能源局"）
        """
        if not text:
            return None
        compact = text.replace(" ", "").replace("　", "")[:1500]
        hits: list[tuple[int, int, int, tuple[str, str]]] = []  # (pass, tier_rank, pos, hit)

        candidates: set[str] = set()
        for rx in _HINT_RES:
            candidates.update(m.group(1) for m in rx.finditer(compact))
        for cand in candidates:
            for alias, hit in self._alias_index.items():
                if not self._alias_supports(hit, domain):
                    continue
                if len(alias) >= 3 and alias in cand:
                    hits.append((0, TIER_RANK.get(hit[0], 9), compact.find(cand), hit[:2]))

        if not hits and not attribution_only:
            for alias, hit in self._alias_index.items():
                if not self._alias_supports(hit, domain):
                    continue
                if len(alias) < 3:
                    continue
                pos = compact.find(alias)
                if pos >= 0:
                    hits.append((1, TIER_RANK.get(hit[0], 9), pos, hit[:2]))

        if not hits:
            return None
        hits.sort(key=lambda h: (h[0], h[1], h[2]))
        return hits[0][3]

    @staticmethod
    def _alias_supports(hit: tuple[str, str, tuple[str, ...]], domain) -> bool:
        value = getattr(domain, "value", domain)
        allowed = hit[2]
        return value is None or not allowed or value in allowed

    def match_author_attribution(self, text: str, domain=None) -> tuple[str, str] | None:
        """只接受“来源/据/转自/电头”等明确署名，避免正文提到机构即误判作者。"""
        return self.match_author_alias(text, domain, attribution_only=True)

    def tier_for_publisher(self, publisher: str, domain=None) -> tuple[str, str] | None:
        compact = (publisher or "").replace(" ", "")
        if not compact:
            return None
        for src in self._authority:
            if not self._supports_domain(src, domain):
                continue
            names = [src["name"], *src.get("aliases", [])]
            if any(compact == n.replace(" ", "") for n in names):
                return src["tier"], src["name"]
        return None

    def is_qualified_open_web(self, url: str, text: str = "") -> bool:
        """开放搜索来源合格性：权威分级命中 或 转载作者命中；黑名单永不采纳。"""
        if self.is_blocked(url):
            return False
        if self.is_designated(url):
            return True
        if self.authority_of(url):
            return True
        return bool(text and self.match_author_alias(text))

    def dedupe_key(self, url: str, publisher: str) -> str:
        """交叉转载去重：同矩阵域名按原始发布主体聚合。"""
        host = (urlparse(url).hostname or "").lower()
        for group in self._dedupe_groups:
            if host in group or any(host.endswith("." + d) for d in group):
                return f"group:{publisher or group[0]}"
        return f"url:{url}"


@lru_cache
def get_source_registry() -> SourceRegistry:
    path = get_settings().source_registry_file
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        logger.error("source registry not found: %s", path)
        data = {}
    return SourceRegistry(data)
