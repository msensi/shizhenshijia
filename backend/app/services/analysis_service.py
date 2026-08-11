"""核验任务业务编排：创建任务、执行管线、查询结果。

Service 层不接触 HTTP 对象；超时/异常在这里落库为任务终态。
"""
import time

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import (
    CODE_INTERNAL_ERROR,
    CODE_QUOTA_EXHAUSTED,
    public_code_of,
)
from app.core.logging import get_logger
from app.models.db_models import Analysis
from app.pipeline.pipeline import PipelineOutput, VerificationPipeline
from app.providers.base import StorageAdapter
from app.repositories.analysis_repo import AnalysisRepository
from app.schemas.result import ProgressStage, ResultStatus, TaskStatus
from app.services import image_service

logger = get_logger(__name__)


class AnalysisService:
    def __init__(
        self, settings: Settings, pipeline: VerificationPipeline, storage: StorageAdapter
    ) -> None:
        self._s = settings
        self._pipeline = pipeline
        self._storage = storage

    def create_task(
        self, session: Session, content: bytes, filename: str | None
    ) -> Analysis:
        """校验图片 -> 存哈希 -> 建任务记录；原图永不落盘。"""
        jpeg = image_service.validate_and_normalize(content, filename, self._s)
        digest = image_service.sha256_hex(jpeg)

        analysis = Analysis(
            status=TaskStatus.queued.value,
            image_hash=digest,
            image_path=None,
            expires_at=None,
        )
        repo = AnalysisRepository(session)
        repo.create(analysis)

        # 原图不落库，但管线需要图片字节：通过临时属性传递，任务结束即弃
        analysis._jpeg_bytes = jpeg  # type: ignore[attr-defined]
        return analysis

    async def execute(self, session: Session, analysis_id: str, jpeg_bytes: bytes) -> None:
        """执行管线并落库终态。所有异常收敛为任务 failed + 错误码。"""
        repo = AnalysisRepository(session)
        analysis = repo.get(analysis_id)
        if analysis is None:
            return
        started = time.monotonic()
        repo.update_fields(analysis, status=TaskStatus.processing.value,
                           progress_stage=ProgressStage.reading_image.value)
        session.commit()

        def _on_stage(stage: ProgressStage) -> None:
            # 管线阶段推进实时落库（前端轮询读取）；失败不阻塞管线
            try:
                repo.update_fields(analysis, progress_stage=stage.value)
                session.commit()
            except Exception:
                # 必须 rollback：否则 session 进入 PendingRollback 状态，
                # 后续所有提交（含最终落库）全部静默失败，任务永远卡 processing
                session.rollback()
                logger.warning("progress stage persist failed analysis=%s", analysis_id)

        try:
            output: PipelineOutput = await self._pipeline.run(
                session, jpeg_bytes, on_stage=_on_stage
            )
            status = TaskStatus.completed.value
            if output.error_code is not None and output.result_status is ResultStatus.insufficient_evidence \
                    and not output.sources and not output.primary_claim:
                status = TaskStatus.failed.value
            repo.update_fields(
                analysis,
                status=status,
                progress_stage=None,
                result_status=output.result_status.value,
                title=output.title,
                summary=output.summary,
                advice=output.advice,
                primary_claim=output.primary_claim,
                domain=output.domain,
                reasons=output.reasons,
                risk_alerts=output.risk_alerts,
                visual_note=output.visual_note,
                sources=output.sources,
                demotion_applied=1 if output.demotion_applied else 0,
                error_code=output.error_code,
                error_public_code=public_code_of(output.error_code),
                latency_ms=output.latency_ms or int((time.monotonic() - started) * 1000),
                pipeline_trace=output.pipeline_trace,
            )
        except Exception:
            logger.exception("analysis %s failed unexpectedly", analysis_id)
            repo.update_fields(
                analysis,
                status=TaskStatus.failed.value,
                progress_stage=None,
                error_code=CODE_INTERNAL_ERROR,
                error_public_code=public_code_of(CODE_INTERNAL_ERROR),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        finally:
            session.commit()
            # 兼容旧数据库：若历史记录意外带有路径，任务结束时强制清除。
            if analysis.image_path:
                self._storage.delete(analysis.image_path)
                repo.update_fields(analysis, image_path=None)
                session.commit()

    def quota_exhausted(self, session: Session) -> bool:
        from datetime import date

        from app.repositories.quota_repo import QuotaRepository
        return QuotaRepository(session).is_exhausted(
            date.today(), self._s.search_daily_quota, self._s.search_daily_cost_limit_fen
        )


QUOTA_ERROR = CODE_QUOTA_EXHAUSTED
