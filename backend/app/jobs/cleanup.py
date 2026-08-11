"""原图到期物理删除定时任务（隐私：IMAGE_RETENTION_DAYS 到期删除）。"""
import asyncio
from datetime import UTC, datetime

from app.core.database import session_scope
from app.core.logging import get_logger
from app.providers.base import StorageAdapter
from app.repositories.analysis_repo import AnalysisRepository

logger = get_logger(__name__)

_CLEANUP_INTERVAL_SECONDS = 3600  # 每小时巡检一次


def cleanup_expired_images(storage: StorageAdapter) -> int:
    """删除所有 expires_at 到期且仍持有原图路径的记录。返回删除数。"""
    now = datetime.now(UTC)
    deleted = 0
    with session_scope() as session:
        repo = AnalysisRepository(session)
        expired = repo.list_expired_images(now)
        for analysis in expired:
            if analysis.image_path:
                storage.delete(analysis.image_path)
                repo.update_fields(analysis, image_path=None)
                deleted += 1
    if deleted:
        logger.info("expired images cleaned count=%d", deleted)
    return deleted


async def cleanup_loop(storage: StorageAdapter) -> None:
    """后台常驻协程：首次立即执行一次，之后按周期巡检。"""
    while True:
        try:
            cleanup_expired_images(storage)
        except Exception:
            logger.exception("cleanup job failed")
        await asyncio.sleep(_CLEANUP_INTERVAL_SECONDS)
