"""Structured logging with request correlation.

Every log line carries the request id of the HTTP request (or WebSocket) that produced it. Raw
audio, transcripts and secrets are never logged by default.
"""

from __future__ import annotations

import asyncio
import logging
import re
import sys
import time
import uuid

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
log = structlog.get_logger("pramana")


def _logged_path(path: str) -> str:
    """Consent secrets travel in one-time link paths and must never enter request logs."""
    return re.sub(r"^(/v1/consent-links/)[^/]+", r"\1[redacted]", path)


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer() if json else structlog.dev.ConsoleRenderer(),
    ]
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )


def _safe_request_id(value: str | None) -> str:
    if value and len(value) <= 64 and all(c.isalnum() or c in "-_." for c in value):
        return value
    return uuid.uuid4().hex


class RequestContextMiddleware:
    """Add request context without BaseHTTPMiddleware's cancellation task group."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", ()))
        rid = _safe_request_id(
            headers.get(REQUEST_ID_HEADER.lower().encode("ascii"), b"").decode("latin-1")
        )
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=rid)
        scope.setdefault("state", {})["request_id"] = rid
        start = time.perf_counter()
        status_code: int | None = None

        async def send_with_context(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                request_id_header = REQUEST_ID_HEADER.lower().encode("ascii")
                message["headers"] = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != request_id_header
                ] + [(request_id_header, rid.encode("ascii"))]
            await send(message)

        try:
            await self.app(scope, receive, send_with_context)
        except asyncio.CancelledError:
            # Client disconnects and server shutdown cancel normal request tasks.
            raise
        except Exception:
            log.exception(
                "request_failed",
                method=scope.get("method", ""),
                path=_logged_path(scope.get("path", "")),
            )
            raise
        else:
            if status_code is not None:
                log.info(
                    "request",
                    method=scope.get("method", ""),
                    path=_logged_path(scope.get("path", "")),
                    status=status_code,
                    ms=round((time.perf_counter() - start) * 1000, 1),
                )
        finally:
            structlog.contextvars.clear_contextvars()
