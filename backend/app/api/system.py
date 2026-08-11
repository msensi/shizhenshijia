"""system 路由：健康检查。"""
from fastapi import APIRouter

from app.api.responses import ok

router = APIRouter(prefix="/api/v1", tags=["system"])

APP_VERSION = "1.0.0"


@router.get("/health")
def health():
    return ok({"status": "ok", "version": APP_VERSION})
