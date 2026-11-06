"""Standalone, local-only emulation of the Gnani surfaces used by voice calls."""

from __future__ import annotations

import argparse
import asyncio
import base64
import io
import json
import struct
import threading
import time
import uuid
import wave
import zlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from voice_bot_common import decode_synthetic_pcm

SSE_CHUNK_BYTES = 4800
SSE_CHUNK_COUNT = 4
TTS_SAMPLE_RATE = 24000


class FakeGnaniEmulator:
    """Serve local stand-ins for Prisma STT and Timbre TTS.

    Binary PCM from the load bot contains a test-only text marker. This server decodes that
    marker for both realtime STT and the unsteered REST confirmation call. It does not contact
    or represent a live Gnani service.
    """

    def __init__(
        self,
        *,
        seed: int = 31,
        stt_delay_s: float = 0.075,
        tts_chunk_delay_s: float = 0.1,
        event_log: Path | None = None,
    ) -> None:
        self.seed = seed
        self.stt_delay_s = stt_delay_s
        self.tts_chunk_delay_s = tts_chunk_delay_s
        self.event_log = event_log
        self._lock = threading.Lock()
        self._latency_sequence = 0
        self._metrics: dict[str, Any] = {
            "stt_rest_requests": 0,
            "tts_rest_requests": 0,
            "tts_sse_requests": 0,
            "synthetic_transcripts_decoded": 0,
            "synthetic_decode_failures": 0,
            "websocket_sessions_opened": 0,
            "websocket_sessions_closed": 0,
            "active_websocket_sessions": 0,
            "peak_active_websocket_sessions": 0,
            "websocket_close_events": [],
        }

    def _increment(self, key: str, amount: int = 1) -> None:
        with self._lock:
            self._metrics[key] += amount

    def _latency(self, base_s: float) -> float:
        with self._lock:
            sequence = self._latency_sequence
            self._latency_sequence += 1
        return max(0.0, base_s + ((sequence % 5) - 2) * 0.005)

    def _decoded(self, audio: bytes) -> str:
        try:
            transcript = decode_synthetic_pcm(audio)
        except ValueError:
            self._increment("synthetic_decode_failures")
            return ""
        self._increment("synthetic_transcripts_decoded")
        return transcript

    def _ws_opened(self, session_id: str) -> None:
        with self._lock:
            self._metrics["websocket_sessions_opened"] += 1
            self._metrics["active_websocket_sessions"] += 1
            self._metrics["peak_active_websocket_sessions"] = max(
                self._metrics["peak_active_websocket_sessions"],
                self._metrics["active_websocket_sessions"],
            )
        self._write_event(
            {
                "event": "websocket_open",
                "session_id": session_id,
                "at_monotonic": time.monotonic(),
            }
        )

    def _ws_closed(
        self,
        session_id: str,
        code: int,
        reason: str,
        *,
        audio_bytes: int,
        transcript_sent: bool,
    ) -> None:
        event = {
            "session_id": session_id,
            "code": code,
            "reason": reason,
            "audio_bytes": audio_bytes,
            "transcript_sent": transcript_sent,
        }
        with self._lock:
            self._metrics["websocket_sessions_closed"] += 1
            self._metrics["active_websocket_sessions"] -= 1
            self._metrics["websocket_close_events"].append(event)
        self._write_event({"event": "websocket_close", **event})

    def _write_event(self, event: dict[str, Any]) -> None:
        if self.event_log is not None:
            self.event_log.parent.mkdir(parents=True, exist_ok=True)
            with self.event_log.open("a", encoding="utf-8") as file:
                file.write(json.dumps(event, separators=(",", ":")) + "\n")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._metrics))

    def _tts_pcm(self, text: str, language: str) -> bytes:
        content_seed = zlib.crc32(f"{self.seed}:{language}:{text}".encode())
        output = bytearray(SSE_CHUNK_BYTES * SSE_CHUNK_COUNT)
        for sample_index in range(len(output) // 2):
            sample = (((sample_index * 37 + content_seed) % 257) - 128) * 100
            struct.pack_into("<h", output, sample_index * 2, sample)
        return bytes(output)

    @staticmethod
    def _wav(pcm_data: bytes, sample_rate: int = TTS_SAMPLE_RATE) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(sample_rate)
            audio.writeframes(pcm_data)
        return output.getvalue()


def create_app(emulator: FakeGnaniEmulator | None = None) -> FastAPI:
    fake = emulator or FakeGnaniEmulator()
    app = FastAPI(title="Pramana local Gnani emulation")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics() -> dict[str, Any]:
        return fake.snapshot()

    @app.post("/stt/v3")
    async def stt_rest(request: Request) -> dict[str, Any]:
        fake._increment("stt_rest_requests")
        form = await request.form()
        audio_file = form.get("audio_file")
        if audio_file is None or not hasattr(audio_file, "read"):
            return {"success": False, "error": {"type": "missing_audio"}}
        audio = await audio_file.read()  # type: ignore[union-attr]
        await asyncio.sleep(fake._latency(fake.stt_delay_s))
        transcript = fake._decoded(audio)
        return {
            "success": True,
            "transcript": transcript,
            "detected_language_code": "en-IN",
            "model": "prisma-v3.0",
            "request_id": uuid.uuid4().hex,
            "processing_time": fake.stt_delay_s,
        }

    @app.post("/api/v1/tts/inference")
    async def tts_rest(request: Request) -> StreamingResponse:
        fake._increment("tts_rest_requests")
        body = await request.json()
        audio_config = body.get("audio_config") or {}
        sample_rate = int(audio_config.get("sample_rate") or TTS_SAMPLE_RATE)
        pcm_data = fake._tts_pcm(str(body.get("text", "")), str(body.get("language", "en-IN")))
        return StreamingResponse(iter([fake._wav(pcm_data, sample_rate)]), media_type="audio/wav")

    @app.post("/api/v1/tts/sse")
    async def tts_sse(request: Request) -> StreamingResponse:
        fake._increment("tts_sse_requests")
        body = await request.json()
        pcm_data = fake._tts_pcm(str(body.get("text", "")), str(body.get("language", "en-IN")))

        async def events() -> AsyncIterator[str]:
            yield 'event: start\ndata: {"status":"streaming_started"}\n\n'
            for chunk_index in range(SSE_CHUNK_COUNT):
                await asyncio.sleep(fake._latency(fake.tts_chunk_delay_s))
                start = chunk_index * SSE_CHUNK_BYTES
                encoded = base64.b64encode(pcm_data[start : start + SSE_CHUNK_BYTES]).decode(
                    "ascii"
                )
                payload = {"chunk_index": chunk_index + 1, "audio": encoded, "is_final": False}
                yield f"event: chunk\ndata: {json.dumps(payload)}\n\n"
            yield 'event: complete\ndata: {"is_final":true}\n\n'

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.websocket("/stt/v3/stream")
    async def stt_realtime(ws: WebSocket) -> None:
        await ws.accept()
        session_id = ws.headers.get("x-api-request-id") or uuid.uuid4().hex
        fake._ws_opened(session_id)
        audio = bytearray()
        transcript_sent = False
        close_code, close_reason = 1006, "socket ended without a close frame"
        headers = ws.headers
        model = headers.get("model", headers.get("x-model", ""))
        config: dict[str, Any] = {"sample_rate": 16000, "chunk_size": 512}
        if model == "prisma-v3.0":
            config["language_code"] = headers.get("language_code", "indic-auto")
            config["format"] = headers.get("format", "verbatim")
        try:
            await ws.send_json({"type": "connected", "message": "ready", "config": config})
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    close_code = int(message.get("code", 1006))
                    close_reason = str(message.get("reason", ""))
                    break
                binary = message.get("bytes")
                if binary is not None:
                    audio.extend(binary)
                    if len(audio) == len(binary):
                        await ws.send_json({"type": "speech_start", "utterance_id": "load-1"})
                    continue
                try:
                    control = json.loads(message.get("text") or "")
                except json.JSONDecodeError:
                    await ws.send_json({"type": "error", "message": "invalid JSON"})
                    continue
                if control.get("type") != "commit":
                    continue
                await ws.send_json({"type": "processing", "timestamp": "load"})
                await asyncio.sleep(fake._latency(fake.stt_delay_s))
                transcript = fake._decoded(bytes(audio))
                await ws.send_json(
                    {
                        "type": "transcript",
                        "text": transcript,
                        "segment_id": session_id,
                        "segment_index": 1,
                        "latency": fake.stt_delay_s * 1000,
                        "detected_language_code": "en-IN",
                        "is_final": True,
                        "audio_duration_ms": len(audio) / 32,
                    }
                )
                transcript_sent = True
        except WebSocketDisconnect as exc:
            close_code = exc.code
            close_reason = str(getattr(exc, "reason", ""))
        finally:
            fake._ws_closed(
                session_id,
                close_code,
                close_reason,
                audio_bytes=len(audio),
                transcript_sent=transcript_sent,
            )

    app.state.emulator = fake
    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8310)
    parser.add_argument("--seed", type=int, default=31)
    parser.add_argument("--stt-delay", type=float, default=0.075)
    parser.add_argument("--tts-chunk-delay", type=float, default=0.1)
    parser.add_argument("--event-log", type=Path)
    args = parser.parse_args()
    fake = FakeGnaniEmulator(
        seed=args.seed,
        stt_delay_s=args.stt_delay,
        tts_chunk_delay_s=args.tts_chunk_delay,
        event_log=args.event_log,
    )
    uvicorn.run(create_app(fake), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
