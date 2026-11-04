"""A local emulation of the documented Gnani realtime STT protocol, for adapter tests.

This is NOT Gnani. It implements only what docs.gnani.ai/api/STT/stt-websocket documents
(headers, ``connected``/``speech_start``/``processing``/``transcript`` events, 1,024-byte binary
frames, ``commit``) and records what the client sent, so tests can check our wire format.
"""

from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import dataclass, field
from typing import Any

import websockets
from websockets.asyncio.server import ServerConnection
from websockets.datastructures import Headers
from websockets.http11 import Request, Response


@dataclass
class FakeGnani:
    reject_status: int | None = None
    confirm_v3: bool = True
    close_code: int | None = None
    transcript: str = "बंद आहे"
    transcripts: list[str] = field(default_factory=list)
    """If set, each commit answers with the next one (then falls back to ``transcript``)."""
    seen_headers: list[Headers] = field(default_factory=list)
    frame_sizes: list[int] = field(default_factory=list)
    port: int = 0
    _loop: asyncio.AbstractEventLoop | None = None
    _stop: asyncio.Event | None = None

    def _process_request(self, _conn: ServerConnection, request: Request) -> Response | None:
        self.seen_headers.append(request.headers)
        if self.reject_status:
            body = json.dumps({"detail": {"error_code": "X", "status_code": self.reject_status}})
            return Response(self.reject_status, "rejected", Headers(), body.encode())
        return None

    async def _handler(self, ws: ServerConnection) -> None:
        h = self.seen_headers[-1]
        config: dict[str, Any] = {"sample_rate": 16000, "chunk_size": 512}
        if self.confirm_v3 and h.get("model") == "prisma-v3.0":
            config |= {"language_code": h.get("language_code"), "format": h.get("format")}
        await ws.send(json.dumps({"type": "connected", "message": "ready", "config": config}))
        if self.close_code:
            await ws.close(self.close_code, "session limit")
            return
        speaking = False
        async for msg in ws:
            if isinstance(msg, bytes):
                self.frame_sizes.append(len(msg))
                if not speaking:
                    speaking = True
                    await ws.send(json.dumps({"type": "speech_start", "utterance_id": "u1"}))
            elif json.loads(msg).get("type") == "commit":
                await ws.send(json.dumps({"type": "processing", "timestamp": "t"}))
                await asyncio.sleep(0.05)
                text = self.transcripts.pop(0) if self.transcripts else self.transcript
                await ws.send(
                    json.dumps(
                        {
                            "type": "transcript",
                            "text": text,
                            "segment_id": "r-seg-1",
                            "segment_index": 1,
                            "latency": 320,
                            "detected_language_code": "mr-IN",
                            "is_final": True,
                            "audio_duration_ms": 900,
                        }
                    )
                )

    async def _serve(self, ready: threading.Event) -> None:
        self._stop = asyncio.Event()
        async with websockets.serve(
            self._handler, "127.0.0.1", 0, process_request=self._process_request
        ) as server:
            self.port = next(iter(server.sockets)).getsockname()[1]
            ready.set()
            await self._stop.wait()

    def start(self) -> FakeGnani:
        ready = threading.Event()

        def run() -> None:
            self._loop = asyncio.new_event_loop()
            self._loop.run_until_complete(self._serve(ready))

        threading.Thread(target=run, daemon=True).start()
        ready.wait(5)
        return self

    def stop(self) -> None:
        if self._loop and self._stop:
            self._loop.call_soon_threadsafe(self._stop.set)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"
