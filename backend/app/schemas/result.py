"""result-v1 契约（PRD 4.4）+ 状态模板文案（PRD 6.2 / 6.3 规范）。

立场基调写死在程序模板；描述性文案结尾不加标点（全局标点规则）。
"""
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class ResultStatus(str, Enum):
    supported = "supported"
    refuted = "refuted"
    disputed = "disputed"
    insufficient_evidence = "insufficient_evidence"
    visual_suspect = "visual_suspect"
    out_of_scope = "out_of_scope"
    unreadable = "unreadable"


class TaskStatus(str, Enum):
    queued = "queued"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class ProgressStage(str, Enum):
    reading_image = "reading_image"
    checking_scope = "checking_scope"
    finding_evidence = "finding_evidence"
    summarizing = "summarizing"


class Source(BaseModel):
    title: str
    publisher: str
    url: str
    quote: str
    published_at: str | None = None


class ResultV1(BaseModel):
    analysis_id: str
    status: TaskStatus
    progress_stage: ProgressStage | None = None
    result_status: ResultStatus | None = None
    title: str | None = None
    summary: str | None = None
    primary_claim: str | None = None
    domain: str | None = None
    reasons: list[str] = Field(default_factory=list)
    risk_alerts: list[str] = Field(default_factory=list)
    advice: str | None = None
    visual_note: str | None = None
    demotion_applied: bool = False
    sources: list[Source] = Field(default_factory=list)
    error_code: int | None = None

    @field_validator("result_status", mode="before")
    @classmethod
    def _status_lenient(cls, v):
        if v is None:
            return None
        try:
            return ResultStatus(v)
        except (ValueError, TypeError):
            return ResultStatus.insufficient_evidence


# ---- 状态 -> 老人话术模板（PRD 6.2 立场基调 + 6.3 标点规则：结尾不加标点）----
STATUS_TEMPLATES: dict[ResultStatus, dict[str, str]] = {
    ResultStatus.supported: {
        "title": "这条与可信来源一致",
        "summary": "这条说法与可信来源一致，您可以信，但仍按官方指引行动",
        "advice": "按官方渠道发布的指引行动；涉及身体、钱的事，再跟家人确认一下更稳妥",
    },
    ResultStatus.refuted: {
        "title": "这条说法与可信来源不符",
        "summary": "这条说法与可信来源不符，您别信、别转、别照做",
        "advice": "不要照这条说法做；已经转发给亲友的话，提醒他们也不要信",
    },
    ResultStatus.disputed: {
        "title": "可信来源之间说法不一致",
        "summary": "可信来源之间说法不一致，您先别行动，等权威结论",
        "advice": "先不要照做；关注官方渠道后续发布的权威结论",
    },
    ResultStatus.insufficient_evidence: {
        "title": "暂时没有足够可靠依据判断真假",
        "summary": "暂时没有足够可靠依据判断真假，您先别照做",
        "advice": "涉及转账、停药、扫码的，一律先不动；拿不准的问家人或打官方电话核实",
    },
    ResultStatus.visual_suspect: {
        "title": "暂时找不到可信来源证实这个画面",
        "summary": "目前没有查到权威来源证实画面中的事件，单张截图也无法判断是否由 AI 生成",
        "advice": "先不要转发；请以政府部门或权威新闻机构的正式报道为准",
    },
    ResultStatus.out_of_scope: {
        "title": "这类内容暂时不在核验范围内",
        "summary": "这类内容暂时不在核验范围内",
        "advice": "您可以换一张健康、政策、防骗或热点相关的图片再试",
    },
    ResultStatus.unreadable: {
        "title": "图片不够清楚",
        "summary": "图片不够清楚，您换一张更清楚的再试",
        "advice": "拍的时候对准文字、光线亮一点，再上传一次",
    },
}

# AI 画面边界说明（PRD 6.2 硬要求：结果必须包含）
VISUAL_NOTE_BOUNDARY = (
    "单张截图无法证明画面由 AI 生成，也可能是特效、影视片段或旧素材；"
    "这里核验的是画面所说的事件有没有可信来源证实"
)

# 配额触顶降级文案（PRD 5.3 搜索预算 + 19.2 Q-429）
QUOTA_EXHAUSTED_NOTE = "今日联网核查额度已用完，结论基于本地权威资料"
