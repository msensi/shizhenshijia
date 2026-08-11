"""scope-v1 契约 + 程序兜底（PRD 4.2）。"""
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class ScopeStatus(str, Enum):
    in_scope = "in_scope"
    out_of_scope = "out_of_scope"
    insufficient_information = "insufficient_information"


class Domain(str, Enum):
    health = "health"
    policy = "policy"
    scam = "scam"
    news = "news"
    non_factual = "non_factual"
    out_of_scope = "out_of_scope"


class ScopeV1(BaseModel):
    schema_version: str = "scope-v1"
    claim_id: str = ""
    scope_status: ScopeStatus = ScopeStatus.insufficient_information
    domain: Domain = Domain.out_of_scope
    rule_id: str = ""
    matched_signals: list[str] = Field(default_factory=list)
    rejection_reason: str | None = None

    @field_validator("scope_status", mode="before")
    @classmethod
    def _status_lenient(cls, v):
        try:
            return ScopeStatus(v)
        except (ValueError, TypeError):
            # 非法状态按信息不足兜底（不联网）
            return ScopeStatus.insufficient_information

    @field_validator("domain", mode="before")
    @classmethod
    def _domain_lenient(cls, v):
        try:
            return Domain(v)
        except (ValueError, TypeError):
            # 分类不在枚举内，强制 out_of_scope
            return Domain.out_of_scope


def parse_scope_v1(payload: dict) -> ScopeV1:
    try:
        scope = ScopeV1.model_validate(payload)
    except Exception:
        return ScopeV1()
    # 状态与域一致性兜底：非 in_scope 时域强制 out_of_scope
    if scope.scope_status is not ScopeStatus.in_scope and scope.domain is Domain.out_of_scope:
        pass
    if scope.scope_status is ScopeStatus.out_of_scope:
        scope.domain = Domain.out_of_scope
    return scope
