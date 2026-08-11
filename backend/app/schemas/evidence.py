"""evidence-v1 契约 + 采纳硬规则（PRD 4.3）。

硬规则：合格来源 + 主体一致 + 直接支持/反驳 + 可展示原文 + 未过期
      => usable_as_evidence = true（程序裁决，模型只判断语义关系）
"""
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class SourceOrigin(str, Enum):
    knowledge_base = "knowledge_base"
    designated_site = "designated_site"
    open_web = "open_web"


class ClaimRelation(str, Enum):
    direct_support = "direct_support"
    direct_refute = "direct_refute"
    mixed = "mixed"
    related_only = "related_only"
    not_related = "not_related"
    cannot_determine = "cannot_determine"


class TimeStatus(str, Enum):
    valid = "valid"
    outdated = "outdated"
    unknown = "unknown"


class EvidenceV1(BaseModel):
    schema_version: str = "evidence-v1"
    claim_id: str = ""
    source_id: str = ""
    source_origin: SourceOrigin = SourceOrigin.open_web
    claim_relation: ClaimRelation = ClaimRelation.cannot_determine
    entity_match: bool = False
    proposition_match: bool = False
    time_status: TimeStatus = TimeStatus.unknown
    supporting_quote: str = ""
    usable_as_evidence: bool = False
    rejection_codes: list[str] = Field(default_factory=list)

    @field_validator("claim_relation", mode="before")
    @classmethod
    def _relation_lenient(cls, v):
        try:
            return ClaimRelation(v)
        except (ValueError, TypeError):
            return ClaimRelation.cannot_determine

    @field_validator("time_status", mode="before")
    @classmethod
    def _time_lenient(cls, v):
        try:
            return TimeStatus(v)
        except (ValueError, TypeError):
            return TimeStatus.unknown


def parse_evidence_v1(payload: dict) -> EvidenceV1:
    try:
        return EvidenceV1.model_validate(payload)
    except Exception:
        return EvidenceV1()


def adjudicate_evidence(ev: EvidenceV1, source_is_qualified: bool) -> EvidenceV1:
    """程序采纳裁决（PRD 4.3 硬规则）。模型输出只做输入，最终由程序决定。"""
    codes: list[str] = list(ev.rejection_codes)
    if not source_is_qualified and "UNQUALIFIED_SOURCE" not in codes:
        codes.append("UNQUALIFIED_SOURCE")
    if not ev.entity_match and "ENTITY_MISMATCH" not in codes:
        codes.append("ENTITY_MISMATCH")
    if not ev.proposition_match and "PROPOSITION_MISMATCH" not in codes:
        codes.append("PROPOSITION_MISMATCH")
    direct = ev.claim_relation in (ClaimRelation.direct_support, ClaimRelation.direct_refute)
    if not direct and "NO_DIRECT_RELATION" not in codes:
        codes.append("NO_DIRECT_RELATION")
    if not ev.supporting_quote.strip() and "NO_QUOTE" not in codes:
        codes.append("NO_QUOTE")
    if ev.time_status is TimeStatus.outdated and "OUTDATED" not in codes:
        codes.append("OUTDATED")

    ev.rejection_codes = codes
    ev.usable_as_evidence = (
        source_is_qualified
        and ev.entity_match
        and ev.proposition_match
        and direct
        and bool(ev.supporting_quote.strip())
        and ev.time_status is not TimeStatus.outdated
    )
    return ev
