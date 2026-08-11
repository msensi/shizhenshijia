"""权威注册表 + authority-v1 契约单测（PRD 5.3 三级筛选）。"""
from app.schemas.authority import adjudicate_authority, parse_authority_v1
from app.services.source_registry import get_source_registry


def _registry():
    return get_source_registry()


def test_gov_domain_hit():
    reg = _registry()
    assert reg.authority_of("https://www.ndrc.gov.cn/xxgk/zcfb/tz/2026/t1.html") == (
        "gov_original", "国家发展和改革委员会",
    )


def test_gov_suffix_fallback_for_unlisted_dept():
    reg = _registry()
    tier, _ = reg.authority_of("https://www.huizhou.gov.cn/zwgk/tzgg/123.html")
    assert tier == "gov_original"


def test_national_media_hit():
    reg = _registry()
    assert reg.authority_of("https://www.news.cn/politics/2026-08/06/c_1.htm")[0] == "national_media"
    assert reg.authority_of("https://news.cctv.com/2026/08/06/a.shtml")[0] == "national_media"


def test_provincial_media_hit():
    reg = _registry()
    assert reg.authority_of("https://www.thepaper.cn/newsDetail_forward_1")[0] == "provincial_media"
    assert reg.authority_of("https://news.ifeng.com/c/abc")[0] == "provincial_media"


def test_blocked_never_qualified():
    reg = _registry()
    assert reg.is_blocked("https://baijiahao.baidu.com/s?id=123")
    assert reg.is_qualified_open_web("https://baijiahao.baidu.com/s?id=123") is False
    assert reg.is_qualified_open_web("https://www.zhihu.com/answer/1") is False


def test_unknown_domain_not_qualified():
    reg = _registry()
    assert reg.authority_of("https://www.some-random-blog.com/post/1") is None
    assert reg.is_qualified_open_web("https://www.some-random-blog.com/post/1") is False


def test_alias_match_source_colon():
    reg = _registry()
    hit = reg.match_author_alias("原标题：充电设施迎来倍增 来源：新华社 2026-08-06")
    assert hit is not None and hit[1] == "新华社" and hit[0] == "national_media"


def test_alias_match_dispatch_style():
    reg = _registry()
    hit = reg.match_author_alias("新华社北京8月6日电 记者6日从国家能源局获悉……")
    assert hit is not None and hit[1] == "新华社"


def test_alias_match_gov_publisher():
    reg = _registry()
    hit = reg.match_author_alias("近日，国家能源局印发《新型电力系统建设十五五规划》发布")
    assert hit is not None and hit[0] == "gov_original"


def test_alias_no_false_positive_on_short_text():
    reg = _registry()
    assert reg.match_author_alias("今天天气不错，大家注意防暑") is None


def test_alias_prefers_highest_tier():
    reg = _registry()
    hit = reg.match_author_alias("据新华社报道，北京日报转发")
    assert hit is not None and hit[0] == "national_media"


def test_authority_parse_and_adjudicate():
    auth = adjudicate_authority(parse_authority_v1({
        "schema_version": "authority-v1",
        "source_tier": "national_media",
        "is_authoritative": True,
        "publisher_name": "新华社",
        "confidence": "high",
    }))
    assert auth.is_authoritative is True


def test_authority_unknown_tier_rejected():
    auth = adjudicate_authority(parse_authority_v1({
        "schema_version": "authority-v1",
        "source_tier": "unknown",
        "publisher_name": "某自媒体",
        "confidence": "medium",
    }))
    assert auth.is_authoritative is False
    assert "TIER_UNKNOWN" in auth.rejection_reasons


def test_authority_low_confidence_rejected():
    auth = adjudicate_authority(parse_authority_v1({
        "schema_version": "authority-v1",
        "source_tier": "gov_original",
        "publisher_name": "某部门",
        "confidence": "low",
    }))
    assert auth.is_authoritative is False


def test_authority_no_publisher_rejected():
    auth = adjudicate_authority(parse_authority_v1({
        "schema_version": "authority-v1",
        "source_tier": "national_media",
        "publisher_name": "",
        "confidence": "high",
    }))
    assert auth.is_authoritative is False
    assert "NO_PUBLISHER" in auth.rejection_reasons


def test_authority_bad_payload_safe():
    auth = adjudicate_authority(parse_authority_v1({"garbage": True}))
    assert auth.is_authoritative is False


def test_registry_respects_domain_routes():
    reg = _registry()
    assert reg.is_designated_for("https://www.piyao.org.cn/x.html", "scam") is True
    assert reg.is_designated_for("https://www.piyao.org.cn/x.html", "health") is False
    assert reg.is_designated_for(
        "https://piyao.kepuchina.cn/rumor/rumordetail?id=1", "health"
    ) is True
    assert reg.authority_of("https://www.nhc.gov.cn/x.html", "policy") is None


def test_attribution_match_does_not_treat_mentioned_org_as_author():
    reg = _registry()
    text = "近日，国家能源局印发新规划，相关内容受到关注"
    assert reg.match_author_alias(text) == ("gov_original", "国家能源局")
    assert reg.match_author_attribution(text, "policy") is None
    assert reg.match_author_attribution("来源：新华社 近日发布消息", "policy") == (
        "national_media", "新华社",
    )


def test_model_publisher_must_map_back_to_registry():
    reg = _registry()
    assert reg.tier_for_publisher("新华社", "news") == ("national_media", "新华社")
    assert reg.tier_for_publisher("某个人账号", "news") is None
