"""核验管线集成测试：scope 拦截、降级矩阵、visual_suspect 隔离、错误码映射。

全链路用 Mock Provider 跑假数据（用户 key 到位前的验证路径）。
"""
import asyncio
import io
import time

import pytest
from PIL import Image

from app.core.errors import CODE_LLM_CONFIG_INVALID, CODE_VISION_FAILED
from app.pipeline.budget import BudgetController, SearchBudget
from app.pipeline.orchestrator import (
    AcceptedEvidence,
    EvidenceChain,
    EvidenceChainResult,
    _distinctive_detail_matches,
    _event_anchor_matches,
)
from app.pipeline.pipeline import VerificationPipeline
from app.providers.bailian_kb import MockKBAdapter
from app.providers.bailian_search import MockSearchAdapter
from app.providers.base import (
    KBCandidate,
    KBRetrieveResult,
    SearchAdapter,
    SearchResult,
    SearchResultItem,
)
from app.providers.dashscope_llm import MockLLMAdapter
from app.schemas.claim import ClaimCandidate, parse_claim_v1
from app.schemas.evidence import ClaimRelation, EvidenceV1, SourceOrigin
from app.schemas.result import ResultStatus
from app.services.source_registry import get_source_registry


def _jpeg() -> bytes:
    img = Image.new("RGB", (100, 100), color=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


CLAIM_HEALTH = {
    "schema_version": "claim-v1",
    "image_readability": "clear",
    "candidates": [{
        "id": "c1", "quote_from_image": "血压正常后就可以停药",
        "normalized_claim": "高血压患者血压正常后可以停用降压药",
        "action_type": "medication_change", "harm_type": "health",
        "urgency": "none", "is_verifiable": True,
        "is_visual_main_subject": True, "visual_prominence": "dominant",
    }],
    "visual_authenticity_question": "false",
}

SCOPE_IN_HEALTH = {
    "schema_version": "scope-v1", "claim_id": "c1",
    "scope_status": "in_scope", "domain": "health",
    "rule_id": "HEALTH_MEDICATION_CHANGE", "matched_signals": ["停药"],
}

SCOPE_OUT = {
    "schema_version": "scope-v1", "claim_id": "c1",
    "scope_status": "out_of_scope", "domain": "out_of_scope",
    "rule_id": "OOS_CAR", "matched_signals": [],
}

CLAIM_POLICY = {
    "schema_version": "claim-v1",
    "image_readability": "clear",
    "candidates": [{
        "id": "c1", "quote_from_image": "政府工作报告提出养老金提高20元",
        "normalized_claim": "2026年政府工作报告提出城乡居民基础养老金最低标准提高20元",
        "action_type": "policy_service", "harm_type": "public",
        "urgency": "none", "is_verifiable": True,
        "is_visual_main_subject": True, "visual_prominence": "dominant",
    }],
    "visual_authenticity_question": "true",
}

SCOPE_IN_POLICY = {
    "schema_version": "scope-v1", "claim_id": "c1",
    "scope_status": "in_scope", "domain": "policy",
    "rule_id": "POLICY_PENSION_STANDARD_UPDATE", "matched_signals": ["养老金"],
}

EVIDENCE_REFUTE = {
    "schema_version": "evidence-v1", "claim_id": "c1", "source_id": "nhc-001",
    "source_origin": "knowledge_base", "claim_relation": "direct_refute",
    "entity_match": True, "proposition_match": True, "time_status": "valid",
    "supporting_quote": "不应自行停用降压药", "usable_as_evidence": True,
    "rejection_codes": [],
}


def _pipeline(settings, llm, kb, search) -> VerificationPipeline:
    get_source_registry.cache_clear()
    return VerificationPipeline(settings, llm, kb, search, get_source_registry())


@pytest.mark.asyncio
async def test_kb_hit_refuted(session, settings):
    """健康域知识库命中 -> refuted，零搜索调用。"""
    llm = MockLLMAdapter()
    llm.queue_vision(CLAIM_HEALTH)
    llm.queue_text(SCOPE_IN_HEALTH)
    llm.queue_text(EVIDENCE_REFUTE)
    kb = MockKBAdapter()
    kb.queue(KBRetrieveResult(ok=True, candidates=[KBCandidate(
        source_id="nhc-001", title="高血压患者能否自行停药",
        publisher="国家卫生健康委员会", url="https://www.nhc.gov.cn/kppypt/x.shtml",
        quote="不应自行停用降压药", score=0.9,
    )]))
    search = MockSearchAdapter()

    out = await _pipeline(settings, llm, kb, search).run(session, _jpeg())
    assert out.result_status is ResultStatus.refuted
    assert out.domain == "health"
    assert out.sources and out.sources[0]["publisher"] == "国家卫生健康委员会"
    assert search.calls == []  # 知识库命中后不再联网
    assert out.pipeline_trace["evidence"]["search_calls"] == 0


@pytest.mark.asyncio
async def test_fast_scope_skips_scope_model_for_clear_health_action(session, settings):
    """明确医疗动作由程序归类，只需排队证据判断响应。"""
    settings = settings.model_copy(update={
        "fast_scope_enabled": True,
        "parallel_evidence_enabled": False,
    })
    llm = MockLLMAdapter()
    llm.queue_vision(CLAIM_HEALTH)
    llm.queue_text(EVIDENCE_REFUTE)
    kb = MockKBAdapter()
    kb.queue(KBRetrieveResult(ok=True, candidates=[KBCandidate(
        source_id="nhc-fast", title="高血压用药提醒",
        publisher="国家卫生健康委员会", url="https://www.nhc.gov.cn/kppypt/fast.shtml",
        quote="不应自行停用降压药", score=0.95,
    )]))

    out = await _pipeline(settings, llm, kb, MockSearchAdapter()).run(session, _jpeg())

    assert out.result_status is ResultStatus.refuted
    assert out.pipeline_trace["scope"]["source"] == "program"
    assert out.pipeline_trace["scope"]["domain"] == "health"


@pytest.mark.asyncio
async def test_parallel_evidence_cancels_slow_search_after_kb_hit(session, settings):
    """知识库快速命中后结束核验，不等待仍在运行的联网搜索。"""
    settings = settings.model_copy(update={
        "fast_scope_enabled": True,
        "parallel_evidence_enabled": True,
    })

    class SlowSearch(SearchAdapter):
        def __init__(self):
            self.started = 0
            self.cancelled = 0

        async def search(self, query, include_domains=None, count=10):
            self.started += 1
            try:
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                self.cancelled += 1
                raise
            return SearchResult(ok=True, items=[])

    llm = MockLLMAdapter()
    llm.queue_vision(CLAIM_HEALTH)
    llm.queue_text(EVIDENCE_REFUTE)
    kb = MockKBAdapter()
    kb.queue(KBRetrieveResult(ok=True, candidates=[KBCandidate(
        source_id="nhc-parallel", title="高血压用药提醒",
        publisher="国家卫生健康委员会", url="https://www.nhc.gov.cn/kppypt/parallel.shtml",
        quote="不应自行停用降压药", score=0.95,
    )]))
    search = SlowSearch()

    started = time.monotonic()
    out = await _pipeline(settings, llm, kb, search).run(session, _jpeg())
    elapsed = time.monotonic() - started

    assert out.result_status is ResultStatus.refuted
    assert elapsed < 0.3
    assert search.started >= 1
    assert search.cancelled == search.started
    assert out.pipeline_trace["evidence"]["stop_reason"] == "knowledge_base_fast_hit"


@pytest.mark.asyncio
async def test_out_of_scope_zero_search(session, settings):
    """AC-04：范围外强制拦截，全程零搜索。"""
    llm = MockLLMAdapter()
    llm.queue_vision({
        **CLAIM_HEALTH,
        "candidates": [{
            "id": "c1", "quote_from_image": "这款车变速箱顿挫严重",
            "normalized_claim": "某品牌汽车变速箱存在质量问题",
            "action_type": "none", "harm_type": "none", "urgency": "none",
            "is_verifiable": True, "is_visual_main_subject": True,
            "visual_prominence": "dominant",
        }],
    })
    llm.queue_text(SCOPE_OUT)
    kb = MockKBAdapter()
    search = MockSearchAdapter()

    out = await _pipeline(settings, llm, kb, search).run(session, _jpeg())
    assert out.result_status is ResultStatus.out_of_scope
    assert search.calls == []
    assert out.pipeline_trace["evidence"] == {} if "evidence" in out.pipeline_trace else True
    assert "evidence" not in out.pipeline_trace  # 未进入证据链


def test_numeric_policy_evidence_must_match_same_distinctive_detail():
    claim = ClaimCandidate.model_validate({
        "id": "c1", "quote_from_image": "到2030年总量超过4000万个",
        "normalized_claim": "到2030年充电基础设施总量超过4000万个",
        "action_type": "policy_service", "harm_type": "public",
    })
    related_but_different_metric = EvidenceV1(
        claim_relation=ClaimRelation.direct_refute,
        entity_match=True, proposition_match=True, time_status="valid",
        supporting_quote="到2030年，建成可支撑超过1.1亿辆电动汽车出行的充电基础设施网络。",
    )
    exact_support = EvidenceV1(
        claim_relation=ClaimRelation.direct_support,
        entity_match=True, proposition_match=True, time_status="valid",
        supporting_quote="到2030年，充电基础设施总量超过4000万个。",
    )

    assert _distinctive_detail_matches(claim, related_but_different_metric) is False
    assert _distinctive_detail_matches(claim, exact_support) is True


def test_public_event_evidence_must_match_same_event_anchors():
    """北海截图不能拿贺州的同类整治新闻当作同一事件。"""
    claim = ClaimCandidate.model_validate({
        "id": "c1",
        "quote_from_image": "8月5日晚北海市公安交管部门联合高德派出所，在马栏村捣毁锂电池黑作坊",
        "normalized_claim": "8月5日晚，北海市公安交管部门联合高德派出所，在马栏村捣毁非法改装电动车锂电池黑作坊",
        "action_type": "public_event", "harm_type": "public",
        "event_anchors": {
            "dates": ["8月5日"],
            "locations": ["北海市", "马栏村"],
            "organizations": ["北海市公安交管部门", "高德派出所"],
            "objects": ["非法改装电动车锂电池黑作坊"],
        },
    })
    unrelated_hezhou = "11月20日，贺州市市场监管部门集中销毁206辆不合格电动自行车。"
    same_event = "8月5日晚，北海市公安交管部门联合高德派出所，在马栏村查处非法改装电动车锂电池黑作坊。"

    assert _event_anchor_matches(claim, unrelated_hezhou) is False
    assert _event_anchor_matches(claim, same_event) is True


def test_single_provincial_source_is_removed_before_final_verdict(settings):
    """一家省级来源未达到交叉印证门槛，不能进入最终确定性裁决。"""
    get_source_registry.cache_clear()
    chain = EvidenceChain(
        settings, MockLLMAdapter(), MockKBAdapter(), MockSearchAdapter(),
        get_source_registry(), BudgetController(settings),
    )

    def accepted(publisher: str, url: str) -> AcceptedEvidence:
        evidence = EvidenceV1(
            claim_relation=ClaimRelation.direct_support,
            entity_match=True,
            proposition_match=True,
            time_status="valid",
            supporting_quote="该消息已经发布",
            usable_as_evidence=True,
        )
        return AcceptedEvidence(
            evidence=evidence,
            title="省级媒体报道",
            publisher=publisher,
            url=url,
            published_at="2026-08-09",
            origin=SourceOrigin.open_web,
            tier="provincial_media",
        )

    one = EvidenceChainResult(accepted=[accepted("北京日报", "https://bjrb.example/a")])
    finalized_one = chain._finalize(one, SearchBudget(max_calls=3))
    assert finalized_one.accepted == []

    two = EvidenceChainResult(accepted=[
        accepted("北京日报", "https://bjrb.example/a"),
        accepted("河北日报", "https://hbrb.example/b"),
    ])
    finalized_two = chain._finalize(two, SearchBudget(max_calls=3))
    assert len(finalized_two.accepted) == 2


@pytest.mark.asyncio
async def test_public_event_kb_similar_news_cannot_short_circuit_web_search(session, settings):
    """模型即使误把相似旧闻判为支持，程序也会拒绝并继续检索。"""
    claim = {
        "schema_version": "claim-v1", "image_readability": "clear",
        "candidates": [{
            "id": "c1",
            "quote_from_image": "8月5日晚北海市公安交管部门联合高德派出所，在马栏村捣毁锂电池黑作坊",
            "normalized_claim": "8月5日晚，北海市公安交管部门联合高德派出所，在马栏村捣毁非法改装电动车锂电池黑作坊",
            "action_type": "public_event", "harm_type": "public", "urgency": "none",
            "is_verifiable": True, "is_visual_main_subject": True, "visual_prominence": "dominant",
            "event_anchors": {
                "dates": ["8月5日"], "locations": ["北海市", "马栏村"],
                "organizations": ["北海市公安交管部门", "高德派出所"],
                "objects": ["非法改装电动车锂电池黑作坊"],
            },
        }],
        "visual_authenticity_question": "true",
    }
    scope = {
        "schema_version": "scope-v1", "claim_id": "c1", "scope_status": "in_scope",
        "domain": "news", "rule_id": "NEWS_PUBLIC_EVENT", "matched_signals": ["公安"],
    }
    misleading_support = {
        "schema_version": "evidence-v1", "claim_id": "c1", "source_id": "py-hezhou",
        "source_origin": "knowledge_base", "claim_relation": "direct_support",
        "entity_match": True, "proposition_match": True, "time_status": "valid",
        "supporting_quote": "11月20日，贺州市市场监管部门集中销毁206辆不合格电动自行车。",
        "usable_as_evidence": True, "rejection_codes": [],
    }
    llm = MockLLMAdapter()
    llm.queue_vision(claim)
    llm.queue_text(scope)
    llm.queue_text(misleading_support)
    kb = MockKBAdapter()
    kb.queue(KBRetrieveResult(ok=True, candidates=[KBCandidate(
        source_id="py-hezhou", title="贺州市集中销毁不合格电动自行车",
        publisher="中国互联网联合辟谣平台", url="https://www.piyao.org.cn/example",
        quote=misleading_support["supporting_quote"], score=0.9,
    )]))
    search = MockSearchAdapter()

    out = await _pipeline(settings, llm, kb, search).run(session, _jpeg())

    assert out.result_status is ResultStatus.visual_suspect
    assert out.sources == []
    assert out.pipeline_trace["evidence"]["knowledge_base"]["accepted"] == 0
    assert len(search.calls) >= 1
    assert "北海市" in search.calls[0][0]


@pytest.mark.asyncio
async def test_visual_suspect_not_insufficient(session, settings):
    """AC-08：画面存疑必须输出 visual_suspect，不得落 insufficient_evidence。"""
    llm = MockLLMAdapter()
    llm.queue_vision({
        "schema_version": "claim-v1", "image_readability": "clear",
        "candidates": [{
            "id": "c1", "quote_from_image": "某地天空出现真龙",
            "normalized_claim": "某地天空出现真实龙的画面",
            "action_type": "public_event", "harm_type": "public",
            "urgency": "none", "is_verifiable": True,
            "is_visual_main_subject": True, "visual_prominence": "dominant",
        }],
        "visual_authenticity_question": "true",
    })
    llm.queue_text({
        "schema_version": "scope-v1", "claim_id": "c1",
        "scope_status": "in_scope", "domain": "news",
        "rule_id": "NEWS_VISUAL_AUTHENTICITY", "matched_signals": ["龙"],
    })
    kb = MockKBAdapter()           # 空命中
    search = MockSearchAdapter()   # 空结果

    out = await _pipeline(settings, llm, kb, search).run(session, _jpeg())
    assert out.result_status is ResultStatus.visual_suspect
    assert out.result_status is not ResultStatus.insufficient_evidence
    assert out.visual_note is not None and "AI" in out.visual_note


@pytest.mark.asyncio
async def test_policy_uses_targeted_route_and_does_not_fall_into_visual_wording(session, settings):
    """政策截图先走 3～5 个来源路由；视觉信号不能覆盖政策结果。"""
    llm = MockLLMAdapter()
    llm.queue_vision(CLAIM_POLICY)
    llm.queue_text(SCOPE_IN_POLICY)
    llm.queue_text({
        **EVIDENCE_REFUTE,
        "claim_relation": "direct_support",
        "supporting_quote": "城乡居民基础养老金最低标准提高20元",
    })
    kb = MockKBAdapter()
    search = MockSearchAdapter()
    # 指定辟谣站没有政策结果；第二次为程序选出的政府工作报告来源组。
    search.queue(SearchResult(ok=True, items=[]))
    search.queue(SearchResult(ok=True, items=[SearchResultItem(
        title="政府工作报告提出城乡居民基础养老金最低标准提高20元",
        url="https://www.gov.cn/yaowen/example.htm",
        snippet="城乡居民基础养老金最低标准提高20元",
        publisher="中国政府网",
    )]))

    out = await _pipeline(settings, llm, kb, search).run(session, _jpeg())

    assert out.result_status is ResultStatus.supported
    assert out.result_status is not ResultStatus.visual_suspect
    assert out.pipeline_trace["evidence"]["open_web"]["route"]["key"] == "policy_government_report"
    assert search.calls[1][1] == [
        "www.gov.cn", "www.news.cn", "www.people.com.cn", "www.cnr.cn", "news.cctv.com"
    ]


@pytest.mark.asyncio
async def test_kb_degraded_falls_to_designated(session, settings):
    """降级矩阵：知识库故障 -> 跳过本层继续指定站。"""
    llm = MockLLMAdapter()
    llm.queue_vision(CLAIM_HEALTH)
    llm.queue_text(SCOPE_IN_HEALTH)
    llm.queue_text(EVIDENCE_REFUTE)  # 指定站证据判断
    kb = MockKBAdapter()
    kb.queue(KBRetrieveResult(ok=False, error="kb down"))
    search = MockSearchAdapter()
    search.queue(SearchResult(ok=True, items=[SearchResultItem(
        title="停药风险科普", url="https://piyao.kepuchina.cn/rumor/rumordetail?id=1",
        snippet="高血压患者不应自行停用降压药", summary="高血压患者不应自行停用降压药",
        publisher="科学辟谣平台", published_at="2026-01-01",
    )]))

    out = await _pipeline(settings, llm, kb, search).run(session, _jpeg())
    assert out.result_status is ResultStatus.refuted
    assert out.pipeline_trace["evidence"]["knowledge_base"]["degraded"] is True
    assert len(search.calls) == 1  # 指定站 1 次调用
    assert search.calls[0][1] is not None  # 带了 include 域名限定


@pytest.mark.asyncio
async def test_search_calls_never_exceed_3(session, settings):
    """AC-11：单次核验搜索调用硬顶 3 次。"""
    llm = MockLLMAdapter()
    llm.queue_vision(CLAIM_HEALTH)
    llm.queue_text(SCOPE_IN_HEALTH)
    # evidence 判断全部返回 cannot_determine -> 永不结论，逼着管线一直搜
    llm.queue_text({**EVIDENCE_REFUTE, "claim_relation": "cannot_determine",
                    "usable_as_evidence": False})
    for _ in range(10):
        llm.queue_text({**EVIDENCE_REFUTE, "claim_relation": "cannot_determine",
                        "usable_as_evidence": False, "supporting_quote": ""})
    kb = MockKBAdapter()
    search = MockSearchAdapter()
    for _ in range(10):
        search.queue(SearchResult(ok=True, items=[SearchResultItem(
            title="无关内容", url="https://www.gov.cn/x", snippet="无关",
        )]))

    out = await _pipeline(settings, llm, kb, search).run(session, _jpeg())
    assert len(search.calls) <= 3
    assert out.pipeline_trace["evidence"]["search_calls"] <= 3
    assert out.result_status is ResultStatus.insufficient_evidence


@pytest.mark.asyncio
async def test_vision_failure_terminal_unreadable(session, settings):
    """降级矩阵：图片模型失败 -> 信息不足终态，不做事实结论，不联网。"""
    llm = MockLLMAdapter()
    llm.queue_vision(None, error="model timeout")  # 调用失败
    kb = MockKBAdapter()
    search = MockSearchAdapter()

    out = await _pipeline(settings, llm, kb, search).run(session, _jpeg())
    assert out.result_status is ResultStatus.unreadable
    assert out.error_code == CODE_VISION_FAILED
    assert search.calls == []


@pytest.mark.asyncio
async def test_llm_config_invalid_maps_5901(session, settings):
    """S-503：key 缺失 -> 5901 配置子码。"""
    llm = MockLLMAdapter()  # 空队列 -> config_invalid
    out = await _pipeline(settings, llm, MockKBAdapter(), MockSearchAdapter()).run(
        session, _jpeg()
    )
    assert out.error_code == CODE_LLM_CONFIG_INVALID


@pytest.mark.asyncio
async def test_quota_exhausted_degrades_gracefully(session, settings):
    """AC-11：日额度触顶 -> 知识库+缓存路径，结果附降级文案。"""
    settings = settings.model_copy(update={"search_daily_quota": 0})
    llm = MockLLMAdapter()
    llm.queue_vision(CLAIM_HEALTH)
    llm.queue_text(SCOPE_IN_HEALTH)
    llm.queue_text(EVIDENCE_REFUTE)
    kb = MockKBAdapter()
    kb.queue(KBRetrieveResult(ok=True, candidates=[KBCandidate(
        source_id="nhc-001", title="停药科普", publisher="国家卫生健康委员会",
        url="https://www.nhc.gov.cn/kppypt/x.shtml", quote="不应自行停用降压药",
    )]))
    search = MockSearchAdapter()

    out = await _pipeline(settings, llm, kb, search).run(session, _jpeg())
    assert search.calls == []  # 触顶后零搜索
    assert out.result_status is ResultStatus.refuted  # 知识库路径仍可用


@pytest.mark.asyncio
async def test_quota_note_appended_when_search_needed(session, settings):
    """触顶且知识库未命中（需要联网）-> 结果附额度降级文案。"""
    settings = settings.model_copy(update={"search_daily_quota": 0})
    llm = MockLLMAdapter()
    llm.queue_vision(CLAIM_HEALTH)
    llm.queue_text(SCOPE_IN_HEALTH)
    kb = MockKBAdapter()           # 空命中 -> 需要联网但被熔断
    search = MockSearchAdapter()

    out = await _pipeline(settings, llm, kb, search).run(session, _jpeg())
    assert search.calls == []
    assert out.result_status is ResultStatus.insufficient_evidence
    assert "额度已用完" in (out.summary or "")


@pytest.mark.asyncio
async def test_no_evidence_insufficient_never_fabricates(session, settings):
    """AC-15 安全红线：无证据时绝不输出 supported/refuted。"""
    llm = MockLLMAdapter()
    llm.queue_vision(CLAIM_HEALTH)
    llm.queue_text(SCOPE_IN_HEALTH)
    kb = MockKBAdapter()
    search = MockSearchAdapter()  # 全空

    out = await _pipeline(settings, llm, kb, search).run(session, _jpeg())
    assert out.result_status is ResultStatus.insufficient_evidence
    assert out.result_status not in (ResultStatus.supported, ResultStatus.refuted)


def test_meta_claim_filtered_as_unreadable(tmp_path):
    """QA P1-2：模糊图上视觉模型输出元描述候选 -> 程序剔除 -> unreadable，不联网。"""
    from app.pipeline.pipeline import _META_CLAIM_RE

    assert _META_CLAIM_RE.search("该图片内容为一份关于补贴的官方通知")
    assert not _META_CLAIM_RE.search("血压正常后可以停用降压药")


def test_dangerous_secondary_claims_always_warn():
    doc = parse_claim_v1({
        "image_readability": "clear",
        "candidates": [
            {
                "id": "c1", "quote_from_image": "今天开始领取补贴",
                "normalized_claim": "今天开始领取养老补贴",
                "action_type": "policy_service", "harm_type": "none",
                "urgency": "none", "is_verifiable": True,
                "is_visual_main_subject": True, "visual_prominence": "dominant",
            },
            {
                "id": "c2", "quote_from_image": "扫码填写验证码",
                "normalized_claim": "领取补贴需要扫码并填写验证码",
                "action_type": "credential_request", "harm_type": "privacy",
                "urgency": "high", "is_verifiable": True,
                "is_visual_main_subject": False, "visual_prominence": "corner",
            },
        ],
    })
    alerts = VerificationPipeline._collect_risk_alerts(doc.candidates)
    assert len(alerts) == 1
    assert "验证码" in alerts[0]
