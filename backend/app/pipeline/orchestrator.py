"""证据链执行：知识库 -> 指定站 -> 开放搜索（PRD 第 3 章流程 + 第 10 章降级）。

每层故障只短路本层，不阻塞整体链路；evidence-v1 调用前先程序粗筛（ADR 4.3）。

开放搜索三级权威筛选（v2，PRD 5.3 落地）：
1. 注册表域名精确匹配（authority_of）——直接定档，抓正文取证据
2. snippet/标题转载作者别名匹配（match_author_alias）——命中即定档，不用抓正文判权威
3. 都不中 -> 抓 Top3 正文，正文里再做别名匹配，仍不中交 authority-v1 模型兜底
"""
import asyncio
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import get_logger
from app.pipeline.budget import BudgetController, PerAnalysisBudgetExceeded, SearchBudget
from app.pipeline.prompts import (
    AUTHORITY_SCHEMA_HINT,
    EVIDENCE_SCHEMA_HINT,
    build_authority_prompt,
    build_evidence_prompt,
)
from app.providers.base import KnowledgeBaseAdapter, LLMAdapter, SearchAdapter
from app.schemas.authority import adjudicate_authority, parse_authority_v1
from app.schemas.claim import ActionType, ClaimCandidate
from app.schemas.evidence import (
    ClaimRelation,
    EvidenceV1,
    SourceOrigin,
    adjudicate_evidence,
    parse_evidence_v1,
)
from app.schemas.scope import Domain
from app.services.page_fetcher import fetch_page_text
from app.services.search_routing import SearchRouter, get_search_router
from app.services.source_registry import TIER_RANK, SourceRegistry

logger = get_logger(__name__)

_MAX_EVIDENCE_JUDGES_PER_LAYER = 3  # ADR 4.3：粗筛后最多送 3 条给文本模型
_NUMBER_UNIT_RE = re.compile(
    r"(?P<number>[\d.]+)\s*(?P<unit>万个|万辆|亿元|万元|亿|万|%|年|月|日|个|辆|千瓦|元|人次|例)"
)
_POLICY_NAME_RE = re.compile(r"《[^》]{2,50}》")
_TIME_UNITS = {"年", "月", "日"}


def _anchor_variants(anchor: str) -> set[str]:
    """北海/北海市、8月5日/2024年8月5日等常见写法统一为可比对候选。"""
    normalized = re.sub(r"\s+", "", anchor)
    variants = {normalized}
    if normalized.endswith(("市", "县", "区")) and len(normalized) > 2:
        variants.add(normalized[:-1])
    date_match = re.search(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日", normalized)
    if date_match:
        variants.add(f"{date_match.group(2)}月{date_match.group(3)}日")
    return {value for value in variants if len(value) >= 2}


def _contains_anchor(text: str, anchor: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    return any(variant in compact for variant in _anchor_variants(anchor))


def _event_anchor_matches(claim: ClaimCandidate, source_text: str) -> bool:
    """公共事件的直接证据必须能确认是同一件事，不能用相似旧闻替代。"""
    if claim.action_type is not ActionType.public_event:
        return True
    anchors = claim.event_anchors
    meaningful = anchors.locations + anchors.dates + anchors.organizations + anchors.objects
    # 公共事件没有任何专有锚点时，无法安全把“同类事件”判为同一事件。
    if not meaningful:
        return False
    location_hit = not anchors.locations or any(
        _contains_anchor(source_text, item) for item in anchors.locations
    )
    if not location_hit:
        return False
    secondary = anchors.dates + anchors.organizations + anchors.objects
    # 有地点时，仍需一个日期、机构或涉事物佐证；没有地点时至少命中两个细节。
    secondary_hits = sum(_contains_anchor(source_text, item) for item in secondary)
    return secondary_hits >= (1 if anchors.locations else 2)


@dataclass
class AcceptedEvidence:
    evidence: EvidenceV1
    title: str
    publisher: str
    url: str
    published_at: str | None
    origin: SourceOrigin
    tier: str


@dataclass
class EvidenceChainResult:
    accepted: list[AcceptedEvidence] = field(default_factory=list)
    search_calls_used: int = 0
    quota_exhausted: bool = False
    layer_trace: dict = field(default_factory=dict)
    stop_reason: str = ""  # kb_hit / designated_hit / open_hit / budget / no_evidence


def _keyword_overlap(claim: str, text: str) -> int:
    """程序粗筛：claim 与候选文本的关键词重叠度（2-gram 字级）。"""
    claim_chars = {claim[i : i + 2] for i in range(max(len(claim) - 1, 1))}
    if not claim_chars:
        return 0
    text_set = {text[i : i + 2] for i in range(max(len(text) - 1, 1))}
    return len(claim_chars & text_set)


def _distinctive_detail_matches(claim: ClaimCandidate, ev: EvidenceV1) -> bool:
    """数字型政策/事件证据必须谈到同一个区分性指标，避免相关报道被误作反证。"""
    if claim.action_type not in (ActionType.policy_service, ActionType.public_event):
        return True
    if ev.claim_relation not in (ClaimRelation.direct_support, ClaimRelation.direct_refute):
        return True

    claim_text = claim.normalized_claim
    quote = ev.supporting_quote
    claim_pairs = [(m.group("number"), m.group("unit")) for m in _NUMBER_UNIT_RE.finditer(claim_text)]
    if not claim_pairs:
        return True
    quote_pairs = [(m.group("number"), m.group("unit")) for m in _NUMBER_UNIT_RE.finditer(quote)]
    claim_names = set(_POLICY_NAME_RE.findall(claim_text))
    quote_names = set(_POLICY_NAME_RE.findall(quote))

    if ev.claim_relation is ClaimRelation.direct_support:
        return bool(set(claim_pairs) & set(quote_pairs) or claim_names & quote_names)

    # 反证可以给出不同数字，但至少要保持同一单位/年份锚点或明确点名同一文件。
    claim_metric_units = {unit for _, unit in claim_pairs if unit not in _TIME_UNITS}
    quote_metric_units = {unit for _, unit in quote_pairs if unit not in _TIME_UNITS}
    if claim_metric_units:
        # 同一年只是时间背景，不能把“4000万个”和“1.1亿辆”变成同一指标。
        return bool(claim_metric_units & quote_metric_units or claim_names & quote_names)

    # 说法只有日期数字时，日期本身就是区分性命题，可用同一时间量纲核对。
    claim_time_units = {unit for _, unit in claim_pairs if unit in _TIME_UNITS}
    quote_time_units = {unit for _, unit in quote_pairs if unit in _TIME_UNITS}
    return bool(claim_time_units & quote_time_units or claim_names & quote_names)


async def _judge(
    llm: LLMAdapter, claim: ClaimCandidate, source_id: str, origin: SourceOrigin,
    title: str, text: str, qualified: bool,
) -> EvidenceV1:
    prompt = build_evidence_prompt(
        claim.normalized_claim, title, text, origin.value, source_id, claim.event_anchor_summary(),
    )
    result = await llm.text_json(prompt, EVIDENCE_SCHEMA_HINT)
    if not result.ok or result.payload is None:
        ev = EvidenceV1(claim_id=claim.id, source_id=source_id, source_origin=origin)
        ev.rejection_codes.append("JUDGE_FAILED")
        ev.usable_as_evidence = False
        return ev
    ev = parse_evidence_v1(result.payload)
    ev.claim_id = claim.id
    ev.source_id = source_id
    ev.source_origin = origin
    # quote 回溯校验：supporting_quote 必须能在来源文本中找到
    # 内嵌坑：正文清洗会吃掉空白字符，模型引用可能带空格——先做空白归一化再比对
    def _squash(s: str) -> str:
        return "".join(s.split())
    if ev.supporting_quote and _squash(ev.supporting_quote) not in _squash(text):
        ev.rejection_codes.append("QUOTE_NOT_TRACEABLE")
        ev.supporting_quote = ""
    if ev.supporting_quote and not _distinctive_detail_matches(claim, ev):
        ev.rejection_codes.append("DISTINCTIVE_DETAIL_MISMATCH")
        ev.proposition_match = False
    if ev.supporting_quote and not _event_anchor_matches(claim, f"{title}\n{text}"):
        ev.rejection_codes.append("EVENT_ANCHOR_MISMATCH")
        ev.entity_match = False
        ev.proposition_match = False
    out = adjudicate_evidence(ev, qualified)
    logger.info(
        "evidence judged src=%s relation=%s entity=%s usable=%s codes=%s quote=%.50s text_head=%.60s",
        source_id[-40:], out.claim_relation.value, out.entity_match,
        out.usable_as_evidence, out.rejection_codes, out.supporting_quote, text,
    )
    return out


class EvidenceChain:
    def __init__(
        self,
        settings: Settings,
        llm: LLMAdapter,
        kb: KnowledgeBaseAdapter,
        search: SearchAdapter,
        registry: SourceRegistry,
        budget_ctrl: BudgetController,
        router: SearchRouter | None = None,
    ) -> None:
        self._s = settings
        self._llm = llm
        self._kb = kb
        self._search = search
        self._registry = registry
        self._budget_ctrl = budget_ctrl
        self._router = router or get_search_router()

    async def run(
        self, session: Session, claim: ClaimCandidate, domain: Domain, budget: SearchBudget
    ) -> EvidenceChainResult:
        if self._s.parallel_evidence_enabled:
            return await self._run_parallel(session, claim, domain, budget)

        result = EvidenceChainResult()

        kb_hit = await self._kb_layer(claim, result)
        result.layer_trace["knowledge_base"] = kb_hit
        if self._conclusive(result):
            result.stop_reason = "kb_hit"
            return self._finalize(result, budget)

        designated_hit = await self._designated_layer(session, claim, domain, budget, result)
        result.layer_trace["designated_site"] = designated_hit
        if self._conclusive(result):
            result.stop_reason = "designated_hit"
            return self._finalize(result, budget)

        open_hit = await self._open_web_layer(session, claim, domain, budget, result)
        result.layer_trace["open_web"] = open_hit
        if self._conclusive(result):
            result.stop_reason = "open_hit"
        elif budget.quota_exhausted:
            result.stop_reason = "budget"
        else:
            result.stop_reason = "no_evidence"
        return self._finalize(result, budget)

    async def _run_parallel(
        self, session: Session, claim: ClaimCandidate, domain: Domain, budget: SearchBudget
    ) -> EvidenceChainResult:
        """三层同时开始；任一层达到证据硬标准即可结束，其余任务安全取消。"""
        result = EvidenceChainResult()
        local_results = {
            "knowledge_base": EvidenceChainResult(),
            "designated_site": EvidenceChainResult(),
            "open_web": EvidenceChainResult(),
        }

        async def _run_kb():
            return await self._kb_layer(claim, local_results["knowledge_base"])

        async def _run_designated():
            return await self._designated_layer(
                session, claim, domain, budget, local_results["designated_site"]
            )

        async def _run_open():
            return await self._open_web_layer(
                session, claim, domain, budget, local_results["open_web"]
            )

        tasks = {
            asyncio.create_task(_run_kb()): "knowledge_base",
            asyncio.create_task(_run_designated()): "designated_site",
            asyncio.create_task(_run_open()): "open_web",
        }
        pending = set(tasks)
        try:
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    layer = tasks[task]
                    try:
                        result.layer_trace[layer] = task.result()
                    except asyncio.CancelledError:
                        result.layer_trace[layer] = {"cancelled": True}
                    except Exception as exc:
                        logger.exception("parallel evidence layer failed layer=%s", layer)
                        result.layer_trace[layer] = {
                            "degraded": True,
                            "reason": type(exc).__name__,
                        }
                    result.accepted.extend(local_results[layer].accepted)

                if self._conclusive(result):
                    winner = next(
                        (tasks[task] for task in done if self._conclusive(local_results[tasks[task]])),
                        "combined",
                    )
                    result.stop_reason = f"{winner}_fast_hit"
                    for task in pending:
                        task.cancel()
                    if pending:
                        await asyncio.gather(*pending, return_exceptions=True)
                    for task in pending:
                        layer = tasks[task]
                        result.layer_trace.setdefault(layer, {"cancelled": True})
                    return self._finalize(result, budget)
        finally:
            leftovers = [task for task in tasks if not task.done()]
            for task in leftovers:
                task.cancel()
            if leftovers:
                await asyncio.gather(*leftovers, return_exceptions=True)

        result.stop_reason = "budget" if budget.quota_exhausted else "no_evidence"
        return self._finalize(result, budget)

    @property
    def _judge_limit(self) -> int:
        if not self._s.parallel_evidence_enabled:
            return _MAX_EVIDENCE_JUDGES_PER_LAYER
        return max(1, min(self._s.fast_evidence_judge_limit, _MAX_EVIDENCE_JUDGES_PER_LAYER))

    @staticmethod
    def _qualifying_relations(result: EvidenceChainResult) -> set[ClaimRelation]:
        """返回达到定论门槛的方向；低层级来源必须有两家独立主体同向印证。"""
        direct = [
            a for a in result.accepted
            if a.evidence.claim_relation in (
                ClaimRelation.direct_support, ClaimRelation.direct_refute
            )
        ]
        qualified: set[ClaimRelation] = set()
        for relation in (ClaimRelation.direct_support, ClaimRelation.direct_refute):
            same_direction = [a for a in direct if a.evidence.claim_relation is relation]
            if any(
                a.tier in {"knowledge_base", "designated", "gov_original", "national_media"}
                for a in same_direction
            ):
                qualified.add(relation)
                continue
            publishers = {
                a.publisher for a in same_direction
                if a.tier in {"provincial_media", "local_official"}
                and a.publisher
            }
            if len(publishers) >= 2:
                qualified.add(relation)
        return qualified

    @classmethod
    def _conclusive(cls, result: EvidenceChainResult) -> bool:
        """A+/A 单条可定论；省级和地市级来源必须有两家独立主体同向印证。"""
        return bool(cls._qualifying_relations(result))

    def _finalize(self, result: EvidenceChainResult, budget: SearchBudget) -> EvidenceChainResult:
        result.search_calls_used = budget.calls_used
        result.quota_exhausted = budget.quota_exhausted
        # 交叉转载去重（PRD 5.2：按原始发布主体）
        seen: set[str] = set()
        deduped: list[AcceptedEvidence] = []
        for a in result.accepted:
            key = self._registry.dedupe_key(a.url, a.publisher)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(a)
        # 提前结束与最终输出必须共用同一证据门槛。否则单家省级/地市级来源
        # 虽不会触发短路，仍可能在汇总阶段被误判为确定结论。
        qualifying = self._qualifying_relations(EvidenceChainResult(accepted=deduped))
        result.accepted = [
            a for a in deduped
            if a.evidence.claim_relation in qualifying
        ][:3]
        return result

    async def _kb_layer(self, claim: ClaimCandidate, result: EvidenceChainResult) -> dict:
        trace = {"candidates": 0, "accepted": 0, "degraded": False}
        kb_res = await self._kb.retrieve(claim.retrieval_query(), self._s.knowledge_base_top_k)
        if not kb_res.ok:
            # 降级：知识库不可用 -> 跳过本层（PRD 10）
            trace["degraded"] = True
            logger.warning("kb layer degraded claim_id=%s", claim.id)
            return trace
        trace["candidates"] = len(kb_res.candidates)
        qualified_candidates = [c for c in kb_res.candidates if c.qualified]
        trace["rejected_by_source_policy"] = len(kb_res.candidates) - len(qualified_candidates)
        ranked = sorted(
            qualified_candidates,
            key=lambda c: _keyword_overlap(claim.retrieval_query(), f"{c.title} {c.quote}"),
            reverse=True,
        )[:self._judge_limit]
        # 零重叠候选基本是语义跑偏（通用词向量近似），跳过省一次模型调用；
        # 全部低重叠时保留 Top1 兜底（防 paraphrase 误杀）
        overlap = [(c, _keyword_overlap(claim.retrieval_query(), f"{c.title} {c.quote}"))
                   for c in ranked]
        to_judge = [c for c, ov in overlap if ov >= 2] or ranked[:1]
        trace["judged"] = len(to_judge)
        # 判定并行（提速：3 次串行 ~9s -> 并行 ~3s）
        judged = await asyncio.gather(*(
            _judge(
                self._llm, claim, cand.source_id or cand.url, SourceOrigin.knowledge_base,
                cand.title, cand.quote or cand.title, qualified=True,
            )
            for cand in to_judge
        ))
        for cand, ev in zip(to_judge, judged, strict=True):
            if ev.usable_as_evidence:
                result.accepted.append(
                    AcceptedEvidence(ev, cand.title, cand.publisher, cand.url,
                                     cand.published_at, SourceOrigin.knowledge_base,
                                     "knowledge_base")
                )
        trace["accepted"] = len(result.accepted)
        return trace

    async def _search_layer(
        self, session: Session, claim: ClaimCandidate, budget: SearchBudget,
        result: EvidenceChainResult, origin: SourceOrigin,
        include_domains: list[str] | None, queries: list[str], domain: Domain,
        *, designated_only: bool = False,
    ) -> dict:
        trace = {"calls": 0, "candidates": 0, "accepted": 0, "degraded": False}
        for query in queries:
            try:
                self._budget_ctrl.consume_or_raise(session, budget)
            except PerAnalysisBudgetExceeded:
                trace["degraded"] = True
                trace["reason"] = "budget"
                break
            search_res = await self._search.search(query, include_domains=include_domains)
            trace["calls"] += 1
            if not search_res.ok:
                # 降级：搜索不可用 -> 用已得证据出结果（PRD 10）
                trace["degraded"] = True
                logger.warning("search layer degraded origin=%s", origin.value)
                break
            qualified = [
                it for it in search_res.items
                if (
                    self._registry.is_designated_for(it.url, domain)
                    if designated_only else self._registry.is_qualified_open_web(it.url)
                )
            ]
            trace["candidates"] += len(qualified)
            ranked = sorted(
                qualified,
                key=lambda it: _keyword_overlap(
                    claim.retrieval_query(), f"{it.title} {it.summary or it.snippet}"
                ),
                reverse=True,
            )[:self._judge_limit]
            # 同一层候选互不依赖，必须并行判定；串行 3 条会轻易吃掉 20~30 秒，
            # 使后续权威搜索还没开始就触发总超时。
            evidence_inputs = [
                (item, item.summary or item.snippet or item.title)
                for item in ranked
            ]
            judged = await asyncio.gather(*(
                _judge(self._llm, claim, item.url, origin, item.title, text, qualified=True)
                for item, text in evidence_inputs
            ))
            for (item, _), ev in zip(evidence_inputs, judged, strict=True):
                if ev.usable_as_evidence:
                    publisher = item.publisher or self._registry.publisher_of(item.url)
                    tier = "designated" if origin is SourceOrigin.designated_site else "unknown"
                    if origin is SourceOrigin.open_web:
                        authority = self._registry.authority_of(item.url, domain)
                        # 政府原始发布可直接定档；媒体域名仍需后续正文作者核验。
                        if authority and authority[0] == "gov_original":
                            tier, publisher = authority
                    result.accepted.append(
                        AcceptedEvidence(
                            ev, item.title, publisher, item.url, item.published_at, origin, tier,
                        )
                    )
            if self._conclusive(result):
                break
        trace["accepted"] = len(result.accepted)
        return trace

    async def _designated_layer(
        self, session: Session, claim: ClaimCandidate, domain: Domain, budget: SearchBudget,
        result: EvidenceChainResult,
    ) -> dict:
        # 指定站层：1 次调用（SPEC 预算口径：指定站 1 + 开放 <=2）。
        # 阿里搜索不支持 include 域名限定（site: 语法无效，实测），
        # 改用平台名关键词召回 + 代码侧 is_designated 白名单过滤（内嵌坑 2026-08-07）。
        designated_domains = self._registry.designated_domains_for(domain)
        query = f"{claim.retrieval_query()} 辟谣 中国互联网联合辟谣平台 科学辟谣平台 国家卫健委"
        return await self._search_layer(
            session, claim, budget, result, SourceOrigin.designated_site,
            designated_domains, [query], domain, designated_only=True,
        )

    async def _open_web_layer(
        self, session: Session, claim: ClaimCandidate, domain: Domain,
        budget: SearchBudget,
        result: EvidenceChainResult,
    ) -> dict:
        """开放搜索：域名只作入口，正文作者/原始发布主体核实后才可作证据。"""
        trace = {"calls": 0, "candidates": 0, "accepted": 0, "degraded": False,
                 "step1_domain": 0, "step2_alias": 0, "step3_fetch": 0}

        # 先由程序按唯一核验对象选出 3～5 个最可能的发布站点。模型只能在这些
        # 站点内搜，不能自由扩大范围；找不到可采纳证据时才走一次全网权威兜底。
        query_text = claim.retrieval_query()
        route = self._router.select(query_text, domain)
        trace["route"] = {"key": route.key, "sites": list(route.sites)}
        targeted = await self._search_layer(
            session, claim, budget, result, SourceOrigin.open_web,
            list(route.sites), [query_text], domain,
        )
        trace["targeted"] = targeted
        if self._conclusive(result):
            trace["calls"] = targeted["calls"]
            trace["candidates"] = targeted["candidates"]
            trace["accepted"] = targeted["accepted"]
            return trace
        if targeted.get("degraded") and targeted.get("reason") == "budget":
            trace["degraded"] = True
            trace["reason"] = "budget"
            return trace

        # 第二次仅用于发现遗漏的权威来源；仍走后面的作者/正文核验，绝不直接采信。
        queries = [f"{query_text} 权威发布"]

        pool: list = []
        seen_urls: set[str] = set()
        # 预算先行（按 query 逐个扣），再并行发搜索（提速：2 次串行 ~3s -> 并行 ~1.5s）
        allowed: list[str] = []
        for query in queries:
            try:
                self._budget_ctrl.consume_or_raise(session, budget)
                allowed.append(query)
            except PerAnalysisBudgetExceeded:
                trace["degraded"] = True
                trace["reason"] = "budget"
                break
        responses = await asyncio.gather(*(
            self._search.search(q, include_domains=None, count=20) for q in allowed
        )) if allowed else []
        trace["calls"] = targeted["calls"] + len(responses)
        for search_res in responses:
            if not search_res.ok:
                trace["degraded"] = True
                logger.warning("open web search degraded claim_id=%s", claim.id)
                continue
            for it in search_res.items:
                if it.url not in seen_urls:
                    seen_urls.add(it.url)
                    pool.append(it)

        # ── 第一级：域名精确匹配；第二级：转载作者别名匹配 ──
        qualified: list[tuple] = []  # (item, tier, publisher_name)
        fallback: list = []
        for it in pool:
            if self._registry.is_blocked(it.url):
                continue
            auth = self._registry.authority_of(it.url, domain)
            if auth:
                qualified.append((it, auth[0], auth[1]))
                trace["step1_domain"] += 1
                continue
            alias_hit = self._registry.match_author_attribution(
                f"{it.title} {it.snippet} {it.publisher}", domain
            )
            if alias_hit:
                qualified.append((it, alias_hit[0], alias_hit[1]))
                trace["step2_alias"] += 1
                continue
            fallback.append(it)

        trace["candidates"] = len(qualified)
        qualified.sort(
            key=lambda q: (
                TIER_RANK.get(q[1], 9),
                -_keyword_overlap(query_text, f"{q[0].title} {q[0].snippet}"),
            )
        )

        # ── 域名命中仅是候选入口；政府原始发布可直接确认，媒体还需确认作者 ──
        top = qualified[:self._judge_limit]
        texts = await asyncio.gather(*(
            fetch_page_text(it.url, claim.retrieval_query()) for it, _, _ in top
        ))
        async def _verified_publisher(item, text: str, candidate_tier: str, candidate_name: str):
            if candidate_tier == "gov_original":
                return candidate_tier, candidate_name
            metadata_hit = self._registry.tier_for_publisher(item.publisher, domain)
            if metadata_hit:
                return metadata_hit
            alias_hit = self._registry.match_author_attribution(
                f"{item.title} {item.snippet} {text[:1500]}", domain
            )
            if alias_hit:
                return alias_hit
            auth_res = await self._llm.text_json(
                build_authority_prompt(item.url, item.title, text), AUTHORITY_SCHEMA_HINT
            )
            if not auth_res.ok or auth_res.payload is None:
                return None
            auth = adjudicate_authority(parse_authority_v1(auth_res.payload))
            if not auth.is_authoritative:
                return None
            return self._registry.tier_for_publisher(auth.publisher_name, domain)

        verification_inputs: list[tuple] = []
        for (item, tier, name), text in zip(top, texts, strict=True):
            if text is None:
                if tier == "gov_original":
                    text = item.snippet or item.title
                else:
                    continue
            verification_inputs.append((item, tier, name, text))
        verified = await asyncio.gather(*(
            _verified_publisher(item, text, tier, name)
            for item, tier, name, text in verification_inputs
        ))
        judge_inputs: list[tuple] = [
            (item, verified_hit[1], verified_hit[0], text)
            for (item, _, _, text), verified_hit in zip(
                verification_inputs, verified, strict=True
            )
            if verified_hit is not None
        ]
        judged = await asyncio.gather(*(
            _judge(self._llm, claim, item.url, SourceOrigin.open_web,
                   item.title, text, qualified=True)
            for item, _, _, text in judge_inputs
        ))
        for (item, name, tier, _), ev in zip(judge_inputs, judged, strict=True):
            if ev.usable_as_evidence:
                result.accepted.append(
                    AcceptedEvidence(ev, item.title, name, item.url,
                                     item.published_at, SourceOrigin.open_web, tier)
                )
        if self._conclusive(result):
            trace["accepted"] = len(result.accepted)
            return trace

        # ── 第三级：抓未合格候选的正文兜底（别名重匹配 -> authority-v1 模型判定）──
        # 抓取并行 -> 权威判定并行 -> 证据判定并行
        fb = fallback[:self._judge_limit]
        fb_texts = await asyncio.gather(*(
            fetch_page_text(it.url, claim.retrieval_query()) for it in fb
        ))
        pairs = [(it, t) for it, t in zip(fb, fb_texts, strict=True) if t]
        trace["step3_fetch"] = len(pairs)

        async def _publisher_of(item, text: str):
            metadata_hit = self._registry.tier_for_publisher(item.publisher, domain)
            if metadata_hit:
                return metadata_hit
            alias_hit = self._registry.match_author_attribution(
                f"{item.title} {item.snippet} {text[:1500]}", domain
            )
            if alias_hit:
                return alias_hit
            auth_res = await self._llm.text_json(
                build_authority_prompt(item.url, item.title, text), AUTHORITY_SCHEMA_HINT
            )
            if not auth_res.ok or auth_res.payload is None:
                return None
            auth = adjudicate_authority(parse_authority_v1(auth_res.payload))
            if not auth.is_authoritative:
                return None
            return self._registry.tier_for_publisher(auth.publisher_name, domain)

        publishers = await asyncio.gather(*(_publisher_of(it, t) for it, t in pairs))
        fb_inputs = [
            (it, t, pub)
            for (it, t), pub in zip(pairs, publishers, strict=True)
            if pub
        ]
        fb_judged = await asyncio.gather(*(
            _judge(self._llm, claim, it.url, SourceOrigin.open_web,
                   it.title, t, qualified=True)
            for it, t, _ in fb_inputs
        ))
        for (item, _, publisher_hit), ev in zip(fb_inputs, fb_judged, strict=True):
            if ev.usable_as_evidence:
                tier, publisher = publisher_hit
                result.accepted.append(
                    AcceptedEvidence(ev, item.title, publisher, item.url,
                                     item.published_at, SourceOrigin.open_web, tier)
                )
        trace["accepted"] = len(result.accepted)
        return trace
