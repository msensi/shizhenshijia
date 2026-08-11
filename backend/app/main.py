"""应用入口：只装配（中间件 + 路由 + 启动钩子），零业务逻辑。"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, analyses, system
from app.api.deps import get_settings
from app.api.responses import error_raw
from app.core.database import init_db
from app.core.errors import CODE_INTERNAL_ERROR, AppError
from app.core.logging import configure_logging, get_logger
from app.jobs.cleanup import cleanup_loop
from app.providers.factory import build_storage

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    init_db()
    settings = get_settings()
    cleanup_task = asyncio.create_task(cleanup_loop(build_storage(settings)))
    logger.info("application startup complete")
    yield
    cleanup_task.cancel()


app = FastAPI(title="是真是假 API", version="1.0.0", lifespan=lifespan)

# CORS：前后端分离开发（vite 5173）；生产同源部署后端 serve 前端 dist
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return error_raw(exc.code, exc.message, exc.http_status)


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("unhandled error on %s", request.url.path)
    return error_raw(CODE_INTERNAL_ERROR, "出了点小问题，您稍后再试", 500)


app.include_router(analyses.router)
app.include_router(system.router)
app.include_router(admin.router)

# 生产环境同源提供 React 页面：一个 Docker 服务即可部署到魔搭
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    _ASSETS = _FRONTEND_DIST / "assets"
    if _ASSETS.is_dir():
        app.mount("/assets", StaticFiles(directory=_ASSETS), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    def frontend_index():
        return FileResponse(_FRONTEND_DIST / "index.html")

    @app.get("/{frontend_path:path}", include_in_schema=False)
    def frontend_fallback(frontend_path: str):
        candidate = (_FRONTEND_DIST / frontend_path).resolve()
        if candidate.is_relative_to(_FRONTEND_DIST.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIST / "index.html")
