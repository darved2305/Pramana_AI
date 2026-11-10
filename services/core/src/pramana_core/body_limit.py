"""Bound request bodies before authentication and parsing."""

from __future__ import annotations

from collections.abc import Callable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodyLimitMiddleware:
    def __init__(
        self, app: ASGIApp, limit_for_path: Callable[[str], int], cors_origins: list[str]
    ) -> None:
        self.app = app
        self.limit_for_path = limit_for_path
        self.cors_origins = cors_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limit_for_path(scope["path"])
        body_buffer = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body_buffer) + len(chunk) > limit:
                request_id = scope.get("state", {}).get("request_id")
                response = JSONResponse(
                    {
                        "error": {
                            "code": "BODY_TOO_LARGE",
                            "message": "this request is too large",
                            "request_id": request_id,
                        }
                    },
                    status_code=413,
                )
                origin = next(
                    (
                        value.decode("latin-1")
                        for name, value in scope["headers"]
                        if name.lower() == b"origin"
                    ),
                    None,
                )
                if origin is not None and (origin in self.cors_origins or "*" in self.cors_origins):
                    response.headers["Access-Control-Allow-Origin"] = (
                        "*" if "*" in self.cors_origins else origin
                    )
                    response.headers.add_vary_header("Origin")
                await response(scope, receive, send)
                return
            body_buffer.extend(chunk)
            if not message.get("more_body", False):
                break
        body = bytes(body_buffer)
        sent = False

        async def replay() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
