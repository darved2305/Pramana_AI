"""Run an ASGI app on a real uvicorn server in a thread, and read Server-Sent Events.

``TestClient`` buffers whole responses, so endless streams and real disconnects need a real
socket. The server runs its own event loop in a daemon thread.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI


@contextmanager
def serve(app: FastAPI) -> Iterator[str]:
    config = uvicorn.Config(
        app, host="127.0.0.1", port=0, log_level="warning", timeout_graceful_shutdown=1
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("uvicorn did not start")
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@dataclass
class Sse:
    event: str
    """``message`` for log events, a control event name, or ``comment`` for heartbeats."""
    id: int | None
    data: Any


def read_sse(response: httpx.Response) -> Iterator[Sse]:
    event, id_, data = "message", None, []
    for line in response.iter_lines():
        if line == "":
            if data:
                text = "\n".join(data)
                yield Sse(event, id_, json.loads(text))
            event, id_, data = "message", None, []
            continue
        if line.startswith(":"):
            yield Sse("comment", None, line[1:].strip())
            continue
        field, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            event = value
        elif field == "id":
            id_ = int(value)
        elif field == "data":
            data.append(value)
