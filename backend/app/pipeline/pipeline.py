"""核验管线主编排：文件校验后的全链路（PRD 第 3 章 + 第 10 章降级矩阵）。

步骤：视觉理解 -> 打分+视觉主体降权 -> scope 拦截 -> 三层证据链 -> result-v1 汇总
安全红线（AC-15）：证据不足时输出确定性真/假结论比例 = 0；
画面类核验不得落入 insufficient_evidence（AC-08）。
"""
import asyncio
import re
import time
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import (
    CODE_ANALYSIS_TIMEOUT,
    CODE_KB_CONFIG_INVALID,
    CODE_LLM_CONFIG_INVALID,
    CODE_SCOPE_PARSE_FAILED,
    CODE_SEARCH_CONFIG_INVALID,
    CODE_VISION_FAILED,
)
from app.core.logging import get_logger
from app.pipeline.budget import BudgetController
from app.pipeline.orchestrator import AcceptedEvidence, EvidenceChain, EvidenceChainResult
from app.pipeline.prompts import (
    CLAIM_PROMPT,
    CLAIM_SCHEMA_HINT,
    SCOPE_PROMPT,
    SCOPE_SCHEMA_HINT,
)
from app.providers.base import KnowledgeBaseAdapter, LLMAdapter, SearchAdapter
from app.schemas.claim import ActionType, ImageReadability, TruthTri, parse_claim_v1
from app.schemas.evidence import ClaimRelation
from app.schemas.result import (
    QUOTA_EXHAUSTED_NOTE,
    STATUS_TEMPLATES,
    VISUAL_NOTE_BOUNDARY,
    ProgressStage,
    ResultStatus,
)
from app.schemas.scope import Domain, ScopeStatus, ScopeV1, parse_scope_v1
from app.services.scoring import select_primary
from app.services.source_registry import SourceRegistry

logger = get_logger(__name__)

# QA P1-2：元描述候选识别（"该图片内容为…的通知""这是一张…广告"等对图片本身的描述，
# 不是图片里的可核验说法）。视觉模型在模糊图上可能无视 prompt 规则仍输出这类候选。
_META_CLAIM_RE = re.compile(
    r"^(该|此|这)?(张|幅|张图|幅图)?图片(内容|所示|显示|中)?(是|为|关于)|"
    r"^(这是|这是一张|此图是|该图是)|"
    r"图片(本身|的)(内容|真实性|类型)|"
    r"^(一份|一张|一条)关于.{0,12}(的)?(官方|宣传|通知|广告|海报)$"
)

@dataclass
class PipelineOutput:
    result_status: ResultStatus
    title: str
    summary: str
    advice: str
    primary_claim: str | None = None
    domain: str | None = None
    reasons: list[str] = field(default_factory=list)
    risk_alerts: list[str] = field(default_factory=list)
    visual_note: str | None = None
    demotion_applied: bool = False
    sources: list[dict] = field(default_factory=list)
    error_code: int | None = None
    latency_ms: int = 0
    pipeline_trace: dict = field(default_factory=dict)


class VerificationPipeline:
    def __init__(
        self,
        settings: Settings,
        llm: LLMAdapter,
        kb: KnowledgeBaseAdapter,
        search: SearchAdapter,
        registry: SourceRegistry,
    ) -> None:
        self._s = settings
        self._llm = llm
        self._chain = EvidenceChain(settings, llm, kb, search, registry, BudgetController(settings))

    def _program_scope(self, primary) -> ScopeV1 | None:
        """明确且已纳入产品范围的动作类型直接归类，省去一次模型调用。"""
        domain_by_action = {
            ActionType.money_transfer: Domain.scam,
            ActionType.credential_request: Domain.scam,
            ActionType.medication_change: Domain.health,
            ActionType.medical_treatment: Domain.health,
            ActionType.general_health: Domain.health,
            ActionType.policy_service: Domain.policy,
            ActionType.public_event: Domain.news,
        }
        domain = domain_by_action.get(primary.action_type)
        if domain is None:
            return None
        return ScopeV1(
            claim_id=primary.id,
            scope_status=ScopeStatus.in_scope,
            domain=domain,
            rule_id=f"FAST_{primary.action_type.value.upper()}",
            matched_signals=[primary.action_type.value],
        )

    async def run(
        self, session: Session, image_bytes: bytes, on_stage=None
    ) -> PipelineOutput:
        started = time.monotonic()
        try:
            return await asyncio.wait_for(
                self._run_inner(session, image_bytes, started, on_stage),
                timeout=self._s.analysis_timeout_seconds,
            )
        except TimeoutError:
            latency = int((time.monotonic() - started) * 1000)
            logger.warning("analysis timeout after %dms", latency)
            return self._error_output(CODE_ANALYSIS_TIMEOUT, latency)

    async def _run_inner(
        self, session: Session, image_bytes: bytes, started: float, on_stage=None
    ) -> PipelineOutput:
        trace: dict = {}

        def _stage(stage) -> None:
            # 进度阶段实时上报（前端轮询展示用）；回调失败不阻塞管线
            if on_stage is None:
                return
            try:
                on_stage(stage)
            except Exception:
                logger.warning("on_stage callback failed stage=%s", stage)

        # 1. 视觉理解（claim-v1）
        t0 = time.monotonic()
        vision = await self._llm.vision_json(image_bytes, CLAIM_PROMPT, CLAIM_SCHEMA_HINT)
        trace["vision"] = {"latency_ms": int((time.monotonic() - t0) * 1000), "ok": vision.ok}
        if vision.config_invalid:
            return self._error_output(CODE_LLM_CONFIG_INVALID, self._lat(started), trace)
        if not vision.ok:
            # 降级：图片模型失败 -> 返回"图片暂时无法理解"，不做事实结论（PRD 10）
            trace["vision"]["degraded"] = True
            return self._terminal(ResultStatus.unreadable, self._lat(started), trace,
                                  error_code=CODE_VISION_FAILED)

        claim_doc = parse_claim_v1(vision.payload or {})
        trace["vision"]["readability"] = claim_doc.image_readability.value
        trace["vision"]["candidate_count"] = len(claim_doc.candidates)
        # QA P1-2 程序兜底：视觉模型在模糊图上可能无视 prompt 规则，输出
        # "该图片内容为一份关于补贴的通知"这类元描述——它不是可核验说法，
        # 放行进证据链会拿弱相关资料输出误导性结论。程序直接剔除。
        before = len(claim_doc.candidates)
        claim_doc.candidates = [
            c for c in claim_doc.candidates if not _META_CLAIM_RE.search(c.normalized_claim)
        ]
        if len(claim_doc.candidates) < before:
            logger.warning(
                "meta-claim filtered: %d -> %d candidates", before, len(claim_doc.candidates)
            )
            trace["vision"]["meta_claim_filtered"] = before - len(claim_doc.candidates)
        if claim_doc.image_readability is ImageReadability.unreadable or not claim_doc.candidates:
            # JSON 解析失败/无可提取候选 -> 按"信息不足"结束，不联网（PRD 10）
            if not vision.ok or claim_doc.image_readability is ImageReadability.unreadable:
                return self._terminal(ResultStatus.unreadable, self._lat(started), trace)
            return self._terminal(ResultStatus.unreadable, self._lat(started), trace,
                                  error_code=None)

        _stage(ProgressStage.checking_scope)

        # 2. 打分排序 + 视觉主体降权（3.1，程序强制）
        selection = select_primary(claim_doc.candidates, self._s.visual_demotion_score)
        trace["scoring"] = {
            "demotion_applied": selection.demotion_applied,
            "demotion_delta": selection.demotion_delta,
            "ranked_scores": [sc.final_score for sc in selection.ranked],
        }
        if selection.primary is None:
            return self._terminal(ResultStatus.unreadable, self._lat(started), trace)
        primary = selection.primary
        risk_alerts = self._collect_risk_alerts(claim_doc.candidates)
        trace["primary_claim"] = primary.normalized_claim
        trace["risk_alert_count"] = len(risk_alerts)

        # 3. 范围判断（scope-v1；非 in_scope 全程零搜索，AC-04）
        scope = self._program_scope(primary) if self._s.fast_scope_enabled else None
        scope_source = "program"
        if scope is None:
            scope_source = "model"
            scope_prompt = (
                f"{SCOPE_PROMPT}\n\nclaim_id：{primary.id}\n"
                f"待判断说法：{primary.normalized_claim}\n"
                f"图片原文：{primary.quote_from_image}\n"
                f"画面真实性存疑：{claim_doc.visual_authenticity_question.value}"
            )
            scope_res = await self._llm.text_json(scope_prompt, SCOPE_SCHEMA_HINT)
            if scope_res.config_invalid:
                return self._error_output(CODE_LLM_CONFIG_INVALID, self._lat(started), trace)
            if not scope_res.ok:
                # scope 模型调用失败（超时/5xx，含降级重试后仍失败）：
                # 图片清楚、claim 已提取，不能误判"图片不清楚"。返回模型失败（E-500），
                # 提示"服务暂时不可用，请稍后再试"，而非让老人以为自己拍照有问题。
                trace["scope"] = {"status": "model_failed", "error": scope_res.error}
                return self._error_output(CODE_SCOPE_PARSE_FAILED, self._lat(started), trace)
            scope = parse_scope_v1(scope_res.payload or {})
        trace["scope"] = {"status": scope.scope_status.value, "domain": scope.domain.value,
                          "rule_id": scope.rule_id, "source": scope_source}
        if scope.scope_status is ScopeStatus.out_of_scope:
            return self._terminal(ResultStatus.out_of_scope, self._lat(started), trace,
                                  primary=primary.normalized_claim,
                                  domain=scope.domain.value,
                                  demotion=selection.demotion_applied,
                                  risk_alerts=risk_alerts)
        if scope.scope_status is ScopeStatus.insufficient_information:
            # 画面存疑例外：主体为画面真实性且无文字说法 -> visual_suspect 路径
            if claim_doc.visual_authenticity_question is TruthTri.true:
                return self._visual_suspect_output(started, trace, primary.normalized_claim,
                                                   selection.demotion_applied, [], risk_alerts)
            return self._terminal(ResultStatus.unreadable, self._lat(started), trace,
                                  primary=primary.normalized_claim,
                                  demotion=selection.demotion_applied,
                                  risk_alerts=risk_alerts)

        _stage(ProgressStage.finding_evidence)

        # 4. 三层证据链
        budget_ctrl = BudgetController(self._s)
        budget = budget_ctrl.new_budget(session)
        chain_result: EvidenceChainResult = await self._chain.run(
            session, primary, scope.domain, budget
        )
        trace["evidence"] = chain_result.layer_trace
        trace["evidence"]["search_calls"] = chain_result.search_calls_used
        trace["evidence"]["stop_reason"] = chain_result.stop_reason

        _stage(ProgressStage.summarizing)

        return self._summarize(
            scope.domain, primary.action_type, claim_doc.visual_authenticity_question,
            primary.normalized_claim,
            selection.demotion_applied, chain_result, started, trace, risk_alerts,
        )

    # ---- 结果汇总（result-v1：7 状态裁决） ----
    def _summarize(
        self, domain: Domain, action_type: ActionType, visual_q: TruthTri, primary_claim: str,
        demotion: bool, chain: EvidenceChainResult, started: float, trace: dict,
        risk_alerts: list[str],
    ) -> PipelineOutput:
        supports = [a for a in chain.accepted if a.evidence.claim_relation is ClaimRelation.direct_support]
        refutes = [a for a in chain.accepted if a.evidence.claim_relation is ClaimRelation.direct_refute]

        # 养老通知等文字政策截图也可能带有“画面真实性”信号。只有公共事件/AI
        # 画面作为主问题时才用 visual_suspect 兜底，不能覆盖政策核验结论。
        is_visual_case = visual_q is TruthTri.true and (
            domain is Domain.news or action_type is ActionType.public_event
        )
        if supports and refutes:
            status = ResultStatus.disputed
        elif refutes:
            status = ResultStatus.refuted
        elif supports:
            status = ResultStatus.supported
        elif is_visual_case:
            # AC-08：画面类无权威报道 -> visual_suspect，不得落 insufficient_evidence
            status = ResultStatus.visual_suspect
        else:
            status = ResultStatus.insufficient_evidence

        tpl = STATUS_TEMPLATES[status]
        sources = [self._source_dict(a) for a in chain.accepted]
        reasons = [a.evidence.supporting_quote for a in chain.accepted if a.evidence.supporting_quote][:3]

        summary, advice = self._scene_wording(status, domain, action_type, tpl)
        if chain.quota_exhausted and chain.layer_trace:
            # 触顶说明只在"确实走了降级联网路径"时附加（19.2：平时不预告）
            summary = f"{summary}；{QUOTA_EXHAUSTED_NOTE}"

        visual_note = VISUAL_NOTE_BOUNDARY if status is ResultStatus.visual_suspect else None
        return PipelineOutput(
            result_status=status,
            title=tpl["title"],
            summary=summary,
            advice=advice,
            primary_claim=primary_claim,
            domain=domain.value,
            reasons=reasons,
            risk_alerts=risk_alerts,
            visual_note=visual_note,
            demotion_applied=demotion,
            sources=sources,
            latency_ms=self._lat(started),
            pipeline_trace=trace,
        )

    @staticmethod
    def _scene_wording(status: ResultStatus, domain: Domain, action_type: ActionType, tpl: dict[str, str]) -> tuple[str, str]:
        """面向用户的建议按场景收敛为有限模板，避免新闻被误说成“办理事项”。"""
        if domain is Domain.news:
            if status is ResultStatus.supported:
                return "已查到与图片中关键细节相符的可信报道", "可以正常了解；转发时保留原发布账号和出处"
            if status is ResultStatus.refuted:
                return "这条消息与可信来源对不上", "先别转发；等当地部门或权威媒体说明"
            if status is ResultStatus.disputed:
                return "不同可信来源对这件事的说法不一致", "先别转发；以当地部门的后续发布为准"
            if status is ResultStatus.visual_suspect:
                return tpl["summary"], "暂时没查到同一事件的可信报道，先别急着转发"
            return tpl["summary"], "先别急着转发；等待当地部门或权威媒体发布"
        if domain is Domain.policy:
            return tpl["summary"], "如需办理，请通过官网、官方 App 或热线核实"
        if domain is Domain.scam:
            return tpl["summary"], "不要转账、扫码或提供验证码；拿不准先问家人或打官方电话"
        if domain is Domain.health or action_type in (ActionType.medication_change, ActionType.medical_treatment):
            return tpl["summary"], "不要自行停药、换药或购买治疗；先咨询医生"
        return tpl["summary"], tpl["advice"]

    @staticmethod
    def _source_dict(a: AcceptedEvidence) -> dict:
        return {
            "title": a.title, "publisher": a.publisher, "url": a.url,
            "quote": a.evidence.supporting_quote, "published_at": a.published_at,
        }

    def _visual_suspect_output(
        self, started, trace, primary_claim, demotion, sources, risk_alerts=None
    ) -> PipelineOutput:
        tpl = STATUS_TEMPLATES[ResultStatus.visual_suspect]
        return PipelineOutput(
            result_status=ResultStatus.visual_suspect, title=tpl["title"],
            summary=tpl["summary"], advice=tpl["advice"], primary_claim=primary_claim,
            domain=Domain.news.value, visual_note=VISUAL_NOTE_BOUNDARY,
            demotion_applied=demotion, sources=sources, risk_alerts=risk_alerts or [],
            latency_ms=self._lat(started), pipeline_trace=trace,
        )

    def _terminal(self, status: ResultStatus, latency: int, trace: dict,
                  primary: str | None = None, domain: str | None = None,
                  demotion: bool = False, error_code: int | None = None,
                  risk_alerts: list[str] | None = None) -> PipelineOutput:
        tpl = STATUS_TEMPLATES[status]
        return PipelineOutput(
            result_status=status, title=tpl["title"], summary=tpl["summary"],
            advice=tpl["advice"], primary_claim=primary, domain=domain,
            demotion_applied=demotion, error_code=error_code,
            risk_alerts=risk_alerts or [],
            latency_ms=latency, pipeline_trace=trace,
        )

    def _error_output(self, code: int, latency: int, trace: dict | None = None) -> PipelineOutput:
        # 配置/超时类错误：任务 failed，错误码进管理页；对外短码由 error_code 映射
        return PipelineOutput(
            result_status=ResultStatus.insufficient_evidence,
            title=STATUS_TEMPLATES[ResultStatus.insufficient_evidence]["title"],
            summary=STATUS_TEMPLATES[ResultStatus.insufficient_evidence]["summary"],
            advice=STATUS_TEMPLATES[ResultStatus.insufficient_evidence]["advice"],
            error_code=code, latency_ms=latency, pipeline_trace=trace or {},
        )

    @staticmethod
    def _lat(started: float) -> int:
        return int((time.monotonic() - started) * 1000)

    @staticmethod
    def _collect_risk_alerts(candidates) -> list[str]:
        """从全部候选中提取危险操作；即使它不是主核验对象也必须提醒。"""
        messages = {
            ActionType.money_transfer: "图片中还出现了转账或付款要求，请先不要转钱",
            ActionType.credential_request: "图片中还要求扫码、提供验证码或个人信息，请不要操作",
            ActionType.medication_change: "图片中还涉及停药、换药或减量，请先咨询医生",
            ActionType.medical_treatment: "图片中还涉及治疗行为，请不要自行尝试或替代正规治疗",
            ActionType.safety_action: "图片中还涉及可能影响人身安全的操作，请先停止并向家人或专业人员确认",
        }
        seen: set[ActionType] = set()
        alerts: list[str] = []
        for candidate in candidates:
            action = candidate.action_type
            if action in messages and action not in seen:
                seen.add(action)
                alerts.append(messages[action])
        return alerts


def config_error_code_for(layer: str) -> int:
    return {"llm": CODE_LLM_CONFIG_INVALID, "kb": CODE_KB_CONFIG_INVALID,
            "search": CODE_SEARCH_CONFIG_INVALID}[layer]
