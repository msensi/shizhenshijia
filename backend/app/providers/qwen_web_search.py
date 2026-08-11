"""千问内置联网搜索适配器。

与 MCP 搜索不同：千问会理解核验任务并改写检索词；当 include_domains 有值时，
turbo 策略严格限制在来源路由选出的 3～5 个站点中搜索。
"""
import time

import httpx

from app.core.config import Settings
from app.core.logging import get_logger
from app.providers.base import SearchAdapter, SearchResult, SearchResultItem

logger = get_logger(__name__)


class QwenWebSearchAdapter(SearchAdapter):
    def __init__(self, settings: Settings) -> None:
        self._s = settings

    async def search(
        self, query: str, include_domains: list[str] | None = None, count: int = 10
    ) -> SearchResult:
        api_key = self._s.search_api_key or self._s.llm_api_key
        if not api_key:
            return SearchResult(ok=False, error="search api key not configured", config_invalid=True)

        search_options: dict = {
            "forced_search": True,
            "search_strategy": "turbo",
            "enable_source": True,
            "enable_citation": True,
        }
        if include_domains:
            # 官方能力上限 25；来源路由自身上限 5，仍在适配层兜底一次。
            search_options["assigned_site_list"] = include_domains[:25]

        prompt = (
            "请为事实核验查找能直接支持或反驳下列说法的权威公开来源。"
            "优先原始发布、正式文件或权威新闻报道；不要把个人账号、自媒体或营销文章当证据。"
            f"待核验说法：{query}"
        )
        body = {
            "model": self._s.integrated_search_model,
            "input": {"messages": [{"role": "user", "content": prompt}]},
            "parameters": {
                "enable_search": True,
                "result_format": "message",
                "search_options": search_options,
            },
        }
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self._s.integrated_search_timeout_seconds) as client:
                response = await client.post(
                    self._s.integrated_search_base_url,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=body,
                )
        except httpx.TimeoutException:
            return SearchResult(ok=False, error="integrated search timeout")
        except httpx.HTTPError as exc:
            logger.warning("integrated search request failed err=%s", type(exc).__name__)
            return SearchResult(ok=False, error="integrated search request failed")

        latency_ms = int((time.monotonic() - started) * 1000)
        if response.status_code in (401, 403, 402):
            return SearchResult(ok=False, error="integrated search auth failed", config_invalid=True)
        if response.status_code != 200:
            return SearchResult(ok=False, error=f"integrated search http {response.status_code}")
        try:
            output = response.json().get("output", {})
            pages = output.get("search_info", {}).get("search_results", [])
        except (ValueError, TypeError):
            return SearchResult(ok=False, error="integrated search malformed response")

        items = [
            SearchResultItem(
                title=str(page.get("title", "")),
                url=str(page.get("url", "")),
                snippet=str(page.get("snippet", "")),
                publisher=str(page.get("site_name", "")),
            )
            for page in pages[:max(1, min(count, 20))]
            if page.get("url")
        ]
        logger.info(
            "integrated search completed latency_ms=%d sources=%d restricted=%s",
            latency_ms, len(items), bool(include_domains),
        )
        return SearchResult(ok=True, items=items, cost_fen=self._s.search_cost_per_call_fen)
