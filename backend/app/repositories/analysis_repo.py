"""analyses 表数据访问。只读写，不含业务逻辑。"""
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.db_models import Analysis


class AnalysisRepository:
    def __init__(self, session: Session) -> None:
        self._s = session

    def create(self, analysis: Analysis) -> Analysis:
        self._s.add(analysis)
        self._s.flush()
        return analysis

    def get(self, analysis_id: str) -> Analysis | None:
        return self._s.get(Analysis, analysis_id)

    def update_fields(self, analysis: Analysis, **fields) -> Analysis:
        for k, v in fields.items():
            setattr(analysis, k, v)
        analysis.updated_at = datetime.now(UTC)
        self._s.flush()
        return analysis

    def list_expired_images(self, now: datetime) -> list[Analysis]:
        stmt = select(Analysis).where(
            Analysis.expires_at.is_not(None),
            Analysis.expires_at <= now,
            Analysis.image_path.is_not(None),
        )
        return list(self._s.scalars(stmt))

    def analytics_page(
        self, date_from: datetime | None, date_to: datetime | None, page: int, limit: int
    ) -> tuple[list[Analysis], int]:
        stmt = select(Analysis)
        if date_from:
            stmt = stmt.where(Analysis.created_at >= date_from)
        if date_to:
            stmt = stmt.where(Analysis.created_at <= date_to)
        total = self._s.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        stmt = stmt.order_by(Analysis.created_at.desc()).offset((page - 1) * limit).limit(limit)
        return list(self._s.scalars(stmt)), total
