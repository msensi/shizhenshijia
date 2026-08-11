"""阿里百炼 WebSearch MCP Adapter（主）+ Mock。

端点：https://dashscope.aliyuncs.com/api/v1/mcps/WebSearch/mcp
协议：JSON-RPC 2.0 over Streamable HTTP，工具 bailian_web_search(query, count)
鉴权：Bearer 复用百炼 LLM_API_KEY（同平台同 key）

内嵌坑（实测验证）：
- 响应体是 JSON-RPC envelope，真正的搜索结果在 result.content[0].text 里——
  那是一个 JSON 字符串，需要二次解析，结构为 {"pages": [{title,snippet,url,hostname,...}]}
- 工具不支持 include_domains 参数；指定站域名限定由编排层代码侧过滤
  （orchestrator._search_layer 已按 registry.is_designated 过滤）
- hostname 是中文站点名（"新浪网"/"腾讯网"），可直接用于权威注册表别名匹配
"""
import json

import httpx

from app.core.config import Settings
from app.core.logging import get_logger
from app.providers.base import SearchAdapter, SearchResult, SearchResultItem

logger = get_logger(__name__)

_MCP_TOOL = "bailian_web_search"


class BailianSearchAdapter(SearchAdapter):
    def __init__(self, settings: Settings, timeout: float = 15.0) -> None:
        self._s = settings
        self._timeout = timeout

    async def search(
        self, query: str, include_domains: list[str] | None = None, count: int = 20
    ) -> SearchResult:
        api_key = self._s.search_api_key or self._s.llm_api_key
        if not api_key:
            return SearchResult(
                ok=False, error="search api key not configured", config_invalid=True
            )
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": _MCP_TOOL,
                "arguments": {"query": query, "count": min(max(count, 1), 20)},
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._s.search_base_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=body,
                )
        except httpx.TimeoutException:
            return SearchResult(ok=False, error="search timeout")
        except httpx.HTTPError as exc:
            logger.warning("search request failed err=%s", type(exc).__name__)
            return SearchResult(ok=False, error="search request failed")

        if resp.status_code in (401, 403):
            return SearchResult(ok=False, error="search auth failed", config_invalid=True)
        if resp.status_code != 200:
            return SearchResult(ok=False, error=f"search http {resp.status_code}")

        try:
            envelope = resp.json()
            if "error" in envelope:
                return SearchResult(ok=False, error="search mcp error")
            contents = envelope.get("result", {}).get("content", [])
            text_payload = next(
                (c.get("text", "") for c in contents if c.get("type") == "text"), ""
            )
            data = json.loads(text_payload) if text_payload else {}
            pages = data.get("pages", [])
        except Exception:
            return SearchResult(ok=False, error="search malformed response")

        items = [
            SearchResultItem(
                title=str(p.get("title", "")),
                url=str(p.get("url", "")),
                snippet=str(p.get("snippet", "")),
                summary="",
                publisher=str(p.get("hostname", "")),
                published_at=None,
            )
            for p in pages
            if p.get("url")
        ]
        return SearchResult(
            ok=True, items=items, cost_fen=self._s.search_cost_per_call_fen
        )


class MockSearchAdapter(SearchAdapter):
    """Mock 搜索：预置结果队列。"""

    def __init__(self) -> None:
        self._queue: list[SearchResult] = []
        self.calls: list[tuple[str, list[str] | None]] = []

    def queue(self, result: SearchResult) -> None:
        self._queue.append(result)

    async def search(
        self, query: str, include_domains: list[str] | None = None, count: int = 10
    ) -> SearchResult:
        self.calls.append((query, include_domains))
        if self._queue:
            return self._queue.pop(0)
        return SearchResult(ok=True, items=[])
