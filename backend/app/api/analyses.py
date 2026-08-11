"""analyses 路由：创建核验任务 / 查询状态结果。只编排，业务在 service。"""
import traceback

from fastapi import APIRouter, BackgroundTasks, Depends, File, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import (
    get_analysis_service,
    get_db,
    quota_guard_error,
)
from app.api.responses import error, ok
from app.core.database import session_scope
from app.core.errors import CODE_INTERNAL_ERROR, CODE_NOT_FOUND, AppError
from app.core.logging import get_logger
from app.schemas.result import TaskStatus
from app.services.analysis_service import AnalysisService

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/analyses", tags=["analyses"])


@router.post("", status_code=202)
async def create_analysis(
    background_tasks: BackgroundTasks,
    file: UploadFile | None = File(default=None),
    session: Session = Depends(get_db),
    service: AnalysisService = Depends(get_analysis_service),
):
    if file is None:
        return error(AppError(CODE_NOT_FOUND, "没有收到图片，您重新选择一张再试"))
    content = await file.read()
    # 隐私：日志只记录类型和大小，不记录用户原始文件名
    logger.info(
        "upload received content_type=%r size=%d bytes",
        file.content_type, len(content),
    )

    # Q-429：日额度触顶时新任务直接熔断（AC-11 / 19.2：平时不预告，触顶才告知）
    if service.quota_exhausted(session):
        return error(quota_guard_error())

    try:
        analysis = service.create_task(session, content, file.filename)
        session.commit()
    except AppError as exc:
        session.rollback()
        logger.warning("upload rejected code=%d msg=%s", exc.code, exc.message)
        return error(exc)
    except Exception as exc:  # 非业务异常（PIL 解码/HEIF 转换/IO 等）：记完整堆栈
        session.rollback()
        logger.error(
            "create_task crashed size=%d: %s\n%s",
            len(content), exc, traceback.format_exc(),
        )
        return error(AppError(CODE_INTERNAL_ERROR, "处理这张图片时出了点问题，您换一张试试"))

    jpeg_bytes = analysis._jpeg_bytes  # type: ignore[attr-defined]
    background_tasks.add_task(_run_task, service, analysis.id, jpeg_bytes)
    logger.info("analysis queued id=%s hash=%s", analysis.id, analysis.image_hash[:12])
    return ok(
        {
            "analysis_id": analysis.id,
            "status": TaskStatus.queued.value,
            "expires_at": analysis.expires_at.isoformat() if analysis.expires_at else None,
        },
        status_code=202,
    )


async def _run_task(service: AnalysisService, analysis_id: str, jpeg_bytes: bytes) -> None:
    """后台任务：独立 session，避免请求会话生命周期问题。"""
    with session_scope() as session:
        await service.execute(session, analysis_id, jpeg_bytes)


@router.get("/{analysis_id}")
def get_analysis(
    analysis_id: str,
    session: Session = Depends(get_db),
):
    from app.repositories.analysis_repo import AnalysisRepository

    analysis = AnalysisRepository(session).get(analysis_id)
    if analysis is None:
        return error(AppError(CODE_NOT_FOUND, "这条记录不存在或已过期", http_status=404))
    data = {
        "analysis_id": analysis.id,
        "status": analysis.status,
        "progress_stage": analysis.progress_stage,
        "result_status": analysis.result_status,
        "title": analysis.title,
        "summary": analysis.summary,
        "primary_claim": analysis.primary_claim,
        "domain": analysis.domain,
        "reasons": analysis.reasons or [],
        "risk_alerts": analysis.risk_alerts or [],
        "advice": analysis.advice,
        "visual_note": analysis.visual_note,
        "demotion_applied": bool(analysis.demotion_applied),
        "sources": analysis.sources or [],
        "error_code": analysis.error_code,
        "error_public_code": analysis.error_public_code,
    }
    return ok(data)
