"""联网检索来源路由：由程序在 3～5 个优先站点中选择检索范围。"""
from dataclasses import dataclass
from functools import lru_cache

import yaml

from app.core.config import get_settings
from app.schemas.scope import Domain


@dataclass(frozen=True)
class SearchRoute:
    key: str
    domain: str
    priority: int
    keywords: tuple[str, ...]
    sites: tuple[str, ...]


class SearchRouter:
    def __init__(self, routes: list[SearchRoute]) -> None:
        self._routes = routes

    def select(self, claim: str, domain: Domain) -> SearchRoute:
        """选择唯一主路线；关键词相同则由配置 priority 裁决，禁止模型任意选域名。"""
        candidates = [route for route in self._routes if route.domain == domain.value]
        if not candidates:
            return SearchRoute("generic", domain.value, 0, (), ())
        hits = [
            route for route in candidates
            if route.keywords and any(keyword in claim for keyword in route.keywords)
        ]
        pool = hits or candidates
        return max(pool, key=lambda route: (route.priority, len(route.keywords), route.key))


@lru_cache
def get_search_router() -> SearchRouter:
    path = get_settings().search_routes_file
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        payload = {}
    routes = [
        SearchRoute(
            key=str(item.get("key", "generic")),
            domain=str(item.get("domain", "")),
            priority=int(item.get("priority", 0)),
            keywords=tuple(str(value) for value in item.get("keywords", []) if value),
            sites=tuple(str(value) for value in item.get("sites", [])[:5] if value),
        )
        for item in payload.get("routes", [])
        if item.get("domain") and item.get("sites")
    ]
    return SearchRouter(routes)
