"""A local, network-level emulation of the Gnani endpoints the core uses, for load tests.

This is NOT Gnani and measures nothing about Gnani. It speaks the documented wire formats
(docs/engineering/GNANI_INTEGRATION.md) so a real core process can be driven end to end for free:

- ``WS /stt/v3/stream``: ``connected``, ``speech_start`` on the first audio, then on ``commit``
  ``processing`` and a final ``transcript``.
- ``POST /stt/v3``: REST transcription (the second, unsteered decode of decisive answers).
- ``POST /api/v1/tts/inference``: a short silent WAV.
- ``POST /api/v1/tts/sse``: ``start``, three ``chunk`` events of raw PCM16, ``complete``.

Transcripts: the "audio" of a load-test clip carries its own text, ``MARK + len + UTF-8``
(``encode_clip``). The emulator finds the mark in what it received and returns that text, so a
bot's answer goes through the real call socket, recognizer session, extractor and engine.

``GET /stats`` reports concurrent and total recognizer sessions, frames and abnormal ends.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import random
import struct
import threading
import time
import wave
from collections.abc import Sequence
from dataclasses import dataclass, field

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

MARK = b"PRAMANA-LOADTEST:"
STT_PLACEHOLDER_DELAY_S = 0.05
TTS_CHUNK_PLACEHOLDER_DELAY_S = 0.05
TTS_CHUNKS_PER_REQUEST = 3
SLOW_FIRST_BYTE_DELAY_S = 0.5


def encode_clip(
    text: str, rate: int = 16_000, pad_s: float = 0.6, *, noise_seed: int | None = None
) -> bytes:
    """A 16 kHz mono PCM16 WAV whose samples spell ``text`` for the emulator to read back."""
    payload = MARK + struct.pack("<H", len(text.encode())) + text.encode()
    if len(payload) % 2:
        payload += b"\x00"
    if noise_seed is None:
        padding = b"\x00\x00" * int(rate * pad_s)
    else:
        rng = random.Random(noise_seed)
        padding = b"".join(
            struct.pack("<h", rng.randint(-512, 512)) for _ in range(int(rate * pad_s))
        )
    pcm = payload + padding
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def decode(data: bytes) -> str:
    """The text carried by the last marked clip in ``data``, or ``""``."""
    i = data.rfind(MARK)
    if i < 0 or i + len(MARK) + 2 > len(data):
        return ""
    (n,) = struct.unpack("<H", data[i + len(MARK) : i + len(MARK) + 2])
    start = i + len(MARK) + 2
    return data[start : start + n].decode(errors="replace")


def add_seeded_noise(data: bytes, seed: int, amplitude: int = 512) -> bytes:
    """Add deterministic low-level PCM noise while preserving an emulator text marker.

    The marker is a test fixture, not speech. Noise is added after its transcript payload when
    present and to the whole buffer otherwise.
    """
    start = 0
    marker = data.rfind(MARK)
    if marker >= 0 and marker + len(MARK) + 2 <= len(data):
        (length,) = struct.unpack("<H", data[marker + len(MARK) : marker + len(MARK) + 2])
        start = marker + len(MARK) + 2 + length
    start += start % 2
    out = bytearray(data)
    rng = random.Random(seed)
    for offset in range(start, len(out) - 1, 2):
        sample = struct.unpack_from("<h", out, offset)[0]
        noise = rng.randint(-amplitude, amplitude)
        struct.pack_into("<h", out, offset, max(-32768, min(32767, sample + noise)))
    return bytes(out)


def _silent_wav(seconds: float = 0.4, rate: int = 24_000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


@dataclass
class Stats:
    fault: str = "none"
    noise_seed: int = 7
    fault_triggered: int = 0
    noise_applied: int = 0
    streams_now: int = 0
    streams_max: int = 0
    streams_total: int = 0
    frames: int = 0
    transcripts: int = 0
    rest_stt: int = 0
    tts_rest: int = 0
    tts_sse: int = 0
    client_dropped: int = 0
    """Sessions the client ended without a normal close (counted, not an error by itself:
    a withdrawn question or barge-in ends its session early)."""
    started: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def as_dict(self) -> dict[str, float | int | str]:
        with self.lock:
            return {k: v for k, v in self.__dict__.items() if k != "lock"}

    def trigger(self, fault: str) -> bool:
        with self.lock:
            if self.fault != fault or self.fault_triggered:
                return False
            self.fault_triggered += 1
            return True


def create_app(stats: Stats) -> Starlette:
    async def stream(ws: WebSocket) -> None:
        h = ws.headers
        await ws.accept()
        with stats.lock:
            stats.streams_now += 1
            stats.streams_total += 1
            stats.streams_max = max(stats.streams_max, stats.streams_now)
        config = {
            "sample_rate": 16000,
            "chunk_size": 512,
            "language_code": h.get("language_code"),
            "format": h.get("format"),
        }
        await ws.send_text(json.dumps({"type": "connected", "message": "ready", "config": config}))
        buf = bytearray()
        speaking = False
        try:
            while True:
                msg = await ws.receive()
                if msg["type"] == "websocket.disconnect":
                    if msg.get("code", 1000) not in (1000, 1001, 1005):
                        with stats.lock:
                            stats.client_dropped += 1
                    return
                if msg.get("bytes") is not None:
                    buf += msg["bytes"]
                    with stats.lock:
                        stats.frames += 1
                    if not speaking:
                        speaking = True
                        await ws.send_text(
                            json.dumps({"type": "speech_start", "utterance_id": "u1"})
                        )
                elif (
                    msg.get("text") is not None and json.loads(msg["text"]).get("type") == "commit"
                ):
                    if stats.trigger("drop"):
                        await ws.close(code=1011, reason="emulated upstream drop")
                        return
                    await ws.send_text(json.dumps({"type": "processing", "timestamp": "t"}))
                    await asyncio.sleep(STT_PLACEHOLDER_DELAY_S)
                    audio = bytes(buf)
                    if stats.trigger("noise"):
                        audio = add_seeded_noise(audio, stats.noise_seed)
                        with stats.lock:
                            stats.noise_applied += 1
                    text = decode(audio)
                    buf.clear()
                    speaking = False
                    with stats.lock:
                        stats.transcripts += 1
                    if stats.trigger("partial"):
                        await ws.send_text(
                            json.dumps({"type": "transcript", "text": "partial", "is_final": False})
                        )
                    if stats.trigger("malformed"):
                        await ws.send_text("{")
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "transcript",
                                "text": text,
                                "segment_id": "seg",
                                "segment_index": 1,
                                "is_final": True,
                                "detected_language_code": "hi-IN",
                            },
                            ensure_ascii=False,
                        )
                    )
        except WebSocketDisconnect:
            return
        finally:
            with stats.lock:
                stats.streams_now -= 1

    async def stt_rest(request: Request) -> JSONResponse:
        if stats.trigger("429"):
            return JSONResponse({"error": "emulated rate limit"}, status_code=429)
        if stats.trigger("5xx"):
            return JSONResponse({"error": "emulated failure"}, status_code=503)
        form = await request.form()
        upload = form.get("audio_file")
        data = await upload.read() if upload is not None and not isinstance(upload, str) else b""
        with stats.lock:
            stats.rest_stt += 1
        return JSONResponse(
            {
                "success": True,
                "transcript": decode(data),
                "detected_language_code": "hi-IN",
                "request_id": "emulated",
                "model": "prisma-v3.0",
            }
        )

    async def tts(_: Request) -> Response:
        if stats.trigger("429"):
            return JSONResponse({"error": "emulated rate limit"}, status_code=429)
        if stats.trigger("5xx"):
            return JSONResponse({"error": "emulated failure"}, status_code=503)
        with stats.lock:
            stats.tts_rest += 1
        return Response(_silent_wav(), media_type="audio/wav")

    async def tts_sse(_: Request) -> Response:
        if stats.trigger("429"):
            return JSONResponse({"error": "emulated rate limit"}, status_code=429)
        if stats.trigger("5xx"):
            return JSONResponse({"error": "emulated failure"}, status_code=503)
        with stats.lock:
            stats.tts_sse += 1
        chunk = base64.b64encode(b"\x00\x00" * 4800).decode()

        async def events():  # type: ignore[no-untyped-def]
            if stats.trigger("slow"):
                await asyncio.sleep(SLOW_FIRST_BYTE_DELAY_S)
            yield "event: start\ndata: {}\n\n"
            for _ in range(TTS_CHUNKS_PER_REQUEST):
                await asyncio.sleep(TTS_CHUNK_PLACEHOLDER_DELAY_S)
                yield f"event: chunk\ndata: {json.dumps({'audio': chunk})}\n\n"
            yield 'event: complete\ndata: {"is_final": true}\n\n'

        return StreamingResponse(events(), media_type="text/event-stream")

    async def stats_route(_: Request) -> JSONResponse:
        return JSONResponse(stats.as_dict())

    return Starlette(
        routes=[
            WebSocketRoute("/stt/v3/stream", stream),
            Route("/stt/v3", stt_rest, methods=["POST"]),
            Route("/api/v1/tts/inference", tts, methods=["POST"]),
            Route("/api/v1/tts/sse", tts_sse, methods=["POST"]),
            Route("/stats", stats_route),
        ]
    )


def serve_in_thread(
    port: int, fault: str = "none", *, noise_seed: int = 7
) -> tuple[Stats, uvicorn.Server]:
    stats = Stats(fault=fault, noise_seed=noise_seed)
    server = uvicorn.Server(
        uvicorn.Config(create_app(stats), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    _SERVER_THREADS[server] = thread
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("emulator did not start")
    return stats, server


_SERVER_THREADS: dict[uvicorn.Server, threading.Thread] = {}


def stop_in_thread(server: uvicorn.Server) -> None:
    """Stop and join an emulator started by serve_in_thread."""
    server.should_exit = True
    thread = _SERVER_THREADS.pop(server, None)
    if thread is None:
        return
    thread.join(timeout=10)
    if thread.is_alive():
        server.force_exit = True
        thread.join(timeout=5)
    if thread.is_alive():
        raise RuntimeError("emulator server did not stop")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Serve the local Gnani protocol emulator.")
    parser.add_argument("--serve", action="store_true", help="run as a foreground server")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument(
        "--fault",
        choices=("none", "drop", "429", "5xx", "slow", "partial", "malformed", "noise"),
        default="none",
    )
    parser.add_argument("--noise-seed", type=int, default=7)
    options = parser.parse_args(argv)
    if not options.serve:
        parser.error("--serve is required")
    uvicorn.run(
        create_app(Stats(fault=options.fault, noise_seed=options.noise_seed)),
        host="127.0.0.1",
        port=options.port,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
