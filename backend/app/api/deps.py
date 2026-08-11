"""API 依赖注入与管理页鉴权。"""

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings
from app.core.database import get_db  # noqa: F401  (re-export for routers)
from app.core.errors import (
    CODE_QUOTA_EXHAUSTED,
    CODE_UNAUTHORIZED,
    AppError,
)
from app.pipeline.pipeline import VerificationPipeline
from app.providers.factory import build_kb, build_llm, build_search, build_storage
from app.services.analysis_service import AnalysisService
from app.services.source_registry import get_source_registry

_bearer = HTTPBearer(auto_error=False)


def require_admin(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> None:
    """管理页单 Token 鉴权（AC-12：无有效 Token 必须 401）。"""
    if not settings.admin_access_token:
        raise AppError(CODE_UNAUTHORIZED, "管理功能未配置", http_status=401)
    if cred is None or cred.credentials != settings.admin_access_token:
        raise AppError(CODE_UNAUTHORIZED, "没有访问权限", http_status=401)


_quota_message = "今天的核验次数用完啦，您明天再来吧"


def quota_guard_error() -> AppError:
    return AppError(CODE_QUOTA_EXHAUSTED, _quota_message, http_status=429)


# ---- Provider / Service 装配（单进程单例） ----
_pipeline: VerificationPipeline | None = None
_analysis_service: AnalysisService | None = None


def get_pipeline(settings: Settings = Depends(get_settings)) -> VerificationPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = VerificationPipeline(
            settings, build_llm(settings), build_kb(settings),
            build_search(settings), get_source_registry(),
        )
    return _pipeline


def get_analysis_service(
    settings: Settings = Depends(get_settings),
    pipeline: VerificationPipeline = Depends(get_pipeline),
) -> AnalysisService:
    global _analysis_service
    if _analysis_service is None:
        _analysis_service = AnalysisService(settings, pipeline, build_storage(settings))
    return _analysis_service


def reset_singletons() -> None:
    """测试用：重置装配缓存。"""
    global _pipeline, _analysis_service
    _pipeline = None
    _analysis_service = None
