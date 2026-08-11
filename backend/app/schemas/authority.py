"""authority-v1 契约：开放搜索第三级兜底的来源权威判定（PRD 5.3）。

模型只在注册表域名匹配 + 转载别名匹配都未命中时介入，
判断"该网页内容的发布主体是否属于权威机构"，不得编造发布主体。
"""
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class SourceTier(str, Enum):
    gov_original = "gov_original"
    national_media = "national_media"
    provincial_media = "provincial_media"
    local_official = "local_official"
    unknown = "unknown"


class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class AuthorityV1(BaseModel):
    schema_version: str = "authority-v1"
    source_tier: SourceTier = SourceTier.unknown
    is_authoritative: bool = False
    is_original_publisher: bool = False
    publisher_name: str = ""
    confidence: Confidence = Confidence.low
    rejection_reasons: list[str] = Field(default_factory=list)

    @field_validator("source_tier", mode="before")
    @classmethod
    def _tier_lenient(cls, v):
        try:
            return SourceTier(v)
        except (ValueError, TypeError):
            return SourceTier.unknown

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence_lenient(cls, v):
        try:
            return Confidence(v)
        except (ValueError, TypeError):
            return Confidence.low


def parse_authority_v1(payload: dict) -> AuthorityV1:
    try:
        return AuthorityV1.model_validate(payload)
    except Exception:
        return AuthorityV1()


def adjudicate_authority(auth: AuthorityV1) -> AuthorityV1:
    """程序裁决（硬规则）：unknown 档位 / low 置信度 / 无发布主体名 一律不采纳。"""
    if auth.source_tier is SourceTier.unknown:
        auth.is_authoritative = False
        if "TIER_UNKNOWN" not in auth.rejection_reasons:
            auth.rejection_reasons.append("TIER_UNKNOWN")
    if auth.confidence is Confidence.low:
        auth.is_authoritative = False
        if "LOW_CONFIDENCE" not in auth.rejection_reasons:
            auth.rejection_reasons.append("LOW_CONFIDENCE")
    if not auth.publisher_name.strip():
        auth.is_authoritative = False
        if "NO_PUBLISHER" not in auth.rejection_reasons:
            auth.rejection_reasons.append("NO_PUBLISHER")
    return auth
