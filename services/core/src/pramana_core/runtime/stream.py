"""Server-Sent Events stream of an investigation's event log (docs/adr/0009).

Wire format (``text/event-stream``)::

    retry: 2000

    event: ready
    data: {"after_seq": 12, "head_seq": 40}

    id: 13
    data: {"seq": 13, "investigation_id": "inv_...", "type": "QuestionAsked", ...}

    : ping

    event: reset
    data: {"reason": "after_seq_ahead", "head_seq": 40}

    event: bye
    data: {"reason": "max_duration", "resume_after_seq": 57}

* Log events use the default ``message`` type and carry ``id: <seq>``, so the browser's
  ``EventSource`` resends ``Last-Event-ID`` when it reconnects and the stream resumes there.
  The ``data`` is the same ``EventEnvelope`` JSON that the polling endpoint returns.
* ``reset``: the client's position is ahead of the log (for example after a database reset).
  Discard local state; the stream continues from the start.
* ``bye``: the server is ending the stream (maximum duration or shutdown). Reconnect from
  ``resume_after_seq``; ``EventSource`` does this automatically.
* ``: ping`` comments are heartbeats. They keep proxies (Next.js rewrites time out idle proxied
  requests after 30 s) from closing the connection, and let the server notice dead clients.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

from starlette.responses import StreamingResponse
from starlette.types import Message, Receive, Scope, Send

from pramana_contracts import EventEnvelope

from ..observability import log
from .broadcast import Subscription

HEADERS = {
    # ``no-transform`` stops gzip middleware (Next.js uses the ``compression`` package, which
    # honours it) from buffering the stream; ``X-Accel-Buffering`` does the same for nginx.
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}
PAGE = 200

FetchEvents = Callable[[int, int], Awaitable[Sequence[EventEnvelope]]]
HeadSeq = Callable[[], Awaitable[int]]


def sse(data: Any = None, *, event: str | None = None, id_: int | None = None) -> bytes:
    lines: list[str] = []
    if id_ is not None:
        lines.append(f"id: {id_}")
    if event is not None:
        lines.append(f"event: {event}")
    payload = data if isinstance(data, str) else json.dumps(data, separators=(",", ":"))
    lines.extend(f"data: {line}" for line in payload.split("\n"))
    return ("\n".join(lines) + "\n\n").encode()


PING = b": ping\n\n"


def parse_last_event_id(value: str | None) -> int | None:
    if value is None or not value.strip().isdigit():
        return None
    return int(value.strip())


async def event_stream(
    sub: Subscription,
    after_seq: int,
    fetch: FetchEvents,
    head_seq: HeadSeq,
    *,
    heartbeat_s: float,
    max_duration_s: float,
    retry_ms: int = 2000,
) -> AsyncIterator[bytes]:
    """Backfill from the log, then follow live commits; never a gap, never a duplicate."""
    started = time.monotonic()
    last = after_seq
    try:
        yield f"retry: {retry_ms}\n\n".encode()
        head = await head_seq()
        if last > head:
            yield sse({"reason": "after_seq_ahead", "head_seq": head}, event="reset")
            last = 0
        yield sse({"after_seq": last, "head_seq": head}, event="ready")
        while True:
            # Drain everything committed so far, page by page.
            while True:
                rows = await fetch(last, PAGE)
                for env in rows:
                    if env.seq <= last:
                        continue  # a commit raced with this read: already sent
                    yield sse(env.model_dump_json(), id_=env.seq)
                    last = env.seq
                if len(rows) < PAGE:
                    break
            if sub.closed:
                yield sse({"reason": "shutdown", "resume_after_seq": last}, event="bye")
                return
            remaining = max_duration_s - (time.monotonic() - started)
            if remaining <= 0:
                yield sse({"reason": "max_duration", "resume_after_seq": last}, event="bye")
                return
            woke = await sub.wait(min(heartbeat_s, remaining))
            if not woke:
                yield PING
    finally:
        sub.close()


class EventStreamResponse(StreamingResponse):
    """A streaming response that drops a client whose socket stops draining.

    uvicorn applies TCP flow control, so ``send`` blocks while a client is not reading. One
    stalled reader must not hold a database page and a task forever: after ``stall_s`` the
    stream is abandoned and the connection closed. The client reconnects with
    ``Last-Event-ID`` and loses nothing.
    """

    media_type = "text/event-stream"

    def __init__(
        self,
        content: AsyncIterator[bytes],
        stall_s: float,
        on_close: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(content, headers=HEADERS, media_type=self.media_type)
        self.stall_s = stall_s
        self.stalled = False
        self._on_close = on_close

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Also runs when the client vanished before the body was ever iterated.
            if self._on_close is not None:
                self._on_close()

    async def stream_response(self, send: Send) -> None:
        async def guarded(message: Message) -> None:
            await asyncio.wait_for(send(message), self.stall_s)

        try:
            await guarded(
                {
                    "type": "http.response.start",
                    "status": self.status_code,
                    "headers": self.raw_headers,
                }
            )
            async for chunk in self.body_iterator:
                await guarded({"type": "http.response.body", "body": chunk, "more_body": True})
            await guarded({"type": "http.response.body", "body": b"", "more_body": False})
        except TimeoutError:
            self.stalled = True
            log.warning("event_stream_stalled", stall_s=self.stall_s)
            aclose = getattr(self.body_iterator, "aclose", None)
            if aclose is not None:
                await aclose()
