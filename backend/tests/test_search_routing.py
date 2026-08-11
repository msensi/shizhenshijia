from app.schemas.scope import Domain
from app.services.search_routing import get_search_router


def test_government_report_routes_to_five_national_authority_sites(settings):
    get_search_router.cache_clear()
    route = get_search_router().select(
        "2026年政府工作报告提出城乡居民基础养老金最低标准再提高20元", Domain.policy
    )
    assert route.key == "policy_government_report"
    assert route.sites == (
        "www.gov.cn", "www.news.cn", "www.people.com.cn", "www.cnr.cn", "news.cctv.com"
    )


def test_pension_without_document_hint_routes_to_social_security_sites(settings):
    get_search_router.cache_clear()
    route = get_search_router().select("城乡居民基础养老金将上调", Domain.policy)
    assert route.key == "policy_pension_social_security"
    assert route.sites == (
        "www.gov.cn", "www.mohrss.gov.cn", "www.people.com.cn", "www.news.cn", "www.cnr.cn"
    )
