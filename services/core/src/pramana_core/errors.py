"""Typed API errors rendered as ``{"error": {"code", "message", "request_id"}}``."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .observability import log


class ApiError(Exception):
    def __init__(
        self, status: int, code: str, message: str, *, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.details = details


def not_found(what: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} not found")


def _body(request: Request, code: str, message: str, **extra: object) -> dict[str, object]:
    rid = getattr(request.state, "request_id", None)
    return {"error": {"code": code, "message": message, "request_id": rid, **extra}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(request: Request, exc: ApiError) -> JSONResponse:
        extra = {"details": exc.details} if exc.details is not None else {}
        return JSONResponse(_body(request, exc.code, exc.message, **extra), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", "")} for e in exc.errors()]
        return JSONResponse(
            _body(request, "VALIDATION_ERROR", "request is invalid", details=details),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            _body(request, "HTTP_ERROR", str(exc.detail)), status_code=exc.status_code
        )

    @app.exception_handler(OperationalError)
    @app.exception_handler(InterfaceError)
    @app.exception_handler(DBAPIError)
    @app.exception_handler(OSError)
    @app.exception_handler(TimeoutError)
    async def _database(request: Request, exc: Exception) -> JSONResponse:
        orig = getattr(exc, "orig", None)
        log.error(
            "dependency_unavailable",
            error_type=type(exc).__name__,
            driver_error=type(orig).__name__ if orig else None,
        )
        return JSONResponse(
            _body(request, "DEPENDENCY_UNAVAILABLE", "a backing service is unavailable"),
            status_code=503,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Exception messages may include personal data or upstream response content.
        log.error("unhandled_error", error_type=type(exc).__name__)
        return JSONResponse(_body(request, "INTERNAL", "internal error"), status_code=500)
