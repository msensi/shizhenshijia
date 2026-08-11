"""admin 路由：管理页数据 + 知识库重建。Bearer Token 鉴权；不返回原图（AC-12）。"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.api.responses import ok
from app.repositories.admin_repo import AdminRepository
from app.repositories.analysis_repo import AnalysisRepository

router = APIRouter(
    prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(require_admin)]
)


@router.get("/analytics")
def get_analytics(
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_db),
):
    items, total = AnalysisRepository(session).analytics_page(date_from, date_to, page, limit)
    data = {
        "items": [
            {
                "analysis_id": a.id,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "domain": a.domain,
                "primary_claim": a.primary_claim,
                "result_status": a.result_status,
                "title": a.title,
                "summary": a.summary,
                "advice": a.advice,
                "reasons": a.reasons or [],
                "risk_alerts": a.risk_alerts or [],
                "sources": a.sources or [],
                "source_count": len(a.sources or []),
                "latency_ms": a.latency_ms,
                "error_code": a.error_code,
                "error_public_code": a.error_public_code,
            }
            for a in items
        ],
        "total": total,
        "page": page,
        "limit": limit,
        "hasMore": page * limit < total,
    }
    return ok(data)


@router.post("/knowledge-base/reindex", status_code=202)
def reindex_knowledge_base(session: Session = Depends(get_db)):
    # MVP：百炼侧索引由用户控制台维护；本端受理 + 审计记录
    AdminRepository(session).log_action("knowledge_base_reindex")
    session.commit()
    return ok({"job_id": "reindex_manual", "status": "queued"}, status_code=202)
