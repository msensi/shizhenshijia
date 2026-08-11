"""ORM 模型（SPEC 第 6 节三表）。只定义结构，不含业务逻辑。"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Date, DateTime, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return f"ana_{uuid.uuid4().hex[:24]}"


class Base(DeclarativeBase):
    pass


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_id)
    status: Mapped[str] = mapped_column(String(16), index=True, default="queued")
    result_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(32), nullable=True)
    primary_claim: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    image_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    advice: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    risk_alerts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    visual_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    sources: Mapped[list | None] = mapped_column(JSON, nullable=True)
    demotion_applied: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_public_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    pipeline_trace: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    progress_stage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SearchQuotaDaily(Base):
    __tablename__ = "search_quota_daily"

    date: Mapped[str] = mapped_column(Date, primary_key=True)
    search_calls: Mapped[int] = mapped_column(Integer, default=0)
    total_cost_fen: Mapped[int] = mapped_column(Integer, default=0)


class AdminAudit(Base):
    __tablename__ = "admin_audit"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
