"""统一响应包组装：{code, data, message}。"""
from typing import Any

from fastapi.responses import JSONResponse

from app.core.errors import AppError


def ok(data: Any, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": 0, "data": data, "message": ""})


def error(err: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=err.http_status,
        content={"code": err.code, "data": None, "message": err.message},
    )


def error_raw(code: int, message: str, http_status: int) -> JSONResponse:
    return JSONResponse(
        status_code=http_status, content={"code": code, "data": None, "message": message}
    )
