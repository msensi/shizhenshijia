"""claim-v1 契约 + 程序校验（PRD 4.1）。

三道防线：json_object -> Pydantic 校验 -> 程序纠偏（枚举强制/缺省降级）。
"""
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class ImageReadability(str, Enum):
    clear = "clear"
    partial = "partial"
    unreadable = "unreadable"


class ActionType(str, Enum):
    money_transfer = "money_transfer"
    credential_request = "credential_request"
    medication_change = "medication_change"
    medical_treatment = "medical_treatment"
    safety_action = "safety_action"
    policy_service = "policy_service"
    purchase = "purchase"
    public_event = "public_event"
    general_health = "general_health"
    none = "none"


class HarmType(str, Enum):
    financial = "financial"
    privacy = "privacy"
    health = "health"
    safety = "safety"
    public = "public"
    none = "none"


class Urgency(str, Enum):
    high = "high"
    medium = "medium"
    none = "none"


class VisualProminence(str, Enum):
    dominant = "dominant"
    prominent = "prominent"
    peripheral = "peripheral"
    corner = "corner"


class TruthTri(str, Enum):
    true = "true"
    false = "false"
    unknown = "unknown"


class EventAnchors(BaseModel):
    """社会事件的可核对细节；缺失时宁可不采纳单条相似报道。"""

    dates: list[str] = Field(default_factory=list, max_length=4)
    locations: list[str] = Field(default_factory=list, max_length=4)
    organizations: list[str] = Field(default_factory=list, max_length=4)
    # 模型会把“电动车 / 电动摩托车 / 锂电池 / 黑作坊”分别列出。
    # 这里必须与清洗上限一致，避免一个多出的细节让整份图片识别结果失效。
    objects: list[str] = Field(default_factory=list, max_length=4)
    source_accounts: list[str] = Field(default_factory=list, max_length=4)

    @field_validator("dates", "locations", "organizations", "objects", "source_accounts", mode="before")
    @classmethod
    def _clean_items(cls, value):
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()][:4]

    def all_items(self) -> list[str]:
        seen: set[str] = set()
        items: list[str] = []
        for group in (self.dates, self.locations, self.organizations, self.objects, self.source_accounts):
            for item in group:
                if item not in seen:
                    seen.add(item)
                    items.append(item)
        return items


class ClaimCandidate(BaseModel):
    id: str = Field(min_length=1)
    quote_from_image: str = Field(min_length=1)
    normalized_claim: str = Field(min_length=1)
    action_type: ActionType = ActionType.none
    harm_type: HarmType = HarmType.none
    urgency: Urgency = Urgency.none
    is_verifiable: bool = True
    is_visual_main_subject: bool = False
    visual_prominence: VisualProminence | None = None
    event_anchors: EventAnchors = Field(default_factory=EventAnchors)

    @field_validator("action_type", mode="before")
    @classmethod
    def _action_lenient(cls, v):
        try:
            return ActionType(v)
        except (ValueError, TypeError):
            return ActionType.none

    @field_validator("harm_type", mode="before")
    @classmethod
    def _harm_lenient(cls, v):
        try:
            return HarmType(v)
        except (ValueError, TypeError):
            return HarmType.none

    @field_validator("urgency", mode="before")
    @classmethod
    def _urgency_lenient(cls, v):
        try:
            return Urgency(v)
        except (ValueError, TypeError):
            return Urgency.none

    @field_validator("is_visual_main_subject", mode="before")
    @classmethod
    def _subject_default_false(cls, v):
        # PRD 4.1：缺失或非法时按 false 处理（宁可误降权，不放过诱饵话术）
        return bool(v) if isinstance(v, bool) else False

    @field_validator("visual_prominence", mode="before")
    @classmethod
    def _prominence_lenient(cls, v):
        if v is None:
            return None
        try:
            return VisualProminence(v)
        except ValueError:
            return None

    def effective_is_main_subject(self) -> bool:
        """peripheral/corner 视为非视觉主体。"""
        if self.visual_prominence in (VisualProminence.peripheral, VisualProminence.corner):
            return False
        return self.is_visual_main_subject

    def retrieval_query(self) -> str:
        """检索带上截图中的专有细节，避免泛化事件词召回相似旧闻。"""
        extras = [item for item in self.event_anchors.all_items() if item not in self.normalized_claim]
        return " ".join([self.normalized_claim, *extras]).strip()

    def event_anchor_summary(self) -> str:
        anchors = self.event_anchors
        groups = {
            "时间": anchors.dates,
            "地点": anchors.locations,
            "机构": anchors.organizations,
            "涉事物": anchors.objects,
            "画面账号": anchors.source_accounts,
        }
        return "；".join(f"{label}：{'、'.join(items)}" for label, items in groups.items() if items)


class ClaimV1(BaseModel):
    schema_version: str = "claim-v1"
    image_readability: ImageReadability = ImageReadability.unreadable
    candidates: list[ClaimCandidate] = Field(default_factory=list, max_length=3)
    visual_authenticity_question: TruthTri = TruthTri.unknown

    @field_validator("image_readability", mode="before")
    @classmethod
    def _readability_lenient(cls, v):
        try:
            return ImageReadability(v)
        except (ValueError, TypeError):
            return ImageReadability.unreadable

    @field_validator("visual_authenticity_question", mode="before")
    @classmethod
    def _tri_lenient(cls, v):
        if isinstance(v, bool):
            return TruthTri.true if v else TruthTri.false
        try:
            return TruthTri(v)
        except (ValueError, TypeError):
            return TruthTri.unknown

    @field_validator("candidates", mode="before")
    @classmethod
    def _cap_candidates(cls, v):
        # 程序校验：候选数最多 3 条
        if isinstance(v, list):
            return v[:3]
        return []


def parse_claim_v1(payload: dict) -> ClaimV1:
    """解析入口：非法输入按 image_readability=unreadable 兜底（信息不足）。"""
    try:
        claim = ClaimV1.model_validate(payload)
    except Exception:
        return ClaimV1(candidates=[])
    # quote 回溯：空 quote 候选已在 Field(min_length=1) 层剔除不掉的，这里再过滤一次
    claim.candidates = [c for c in claim.candidates if c.quote_from_image.strip()]
    return claim
