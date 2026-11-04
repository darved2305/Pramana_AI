# No ``from __future__ import annotations``: FastAPI resolves dependency annotations at runtime.
"""Voice routes: REST transcription, synthesis, and a realtime relay to Gnani.

Browsers cannot set custom WebSocket headers, and the API key must stay server-side, so the
browser streams PCM to ``/v1/voice/stream`` and the core relays it to Prisma with per-session
context headers. Raw audio is never stored or logged.
"""

import asyncio
import contextlib
import json
import time
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import Response
from pydantic import ValidationError

from pramana_contracts import (
    MediaClientMessage,
    MediaServerMessage,
    StaffRole,
    SttResult,
    TtsRequest,
)

from ..auth.deps import require_staff, staff_on_socket
from ..errors import ApiError
from ..observability import log
from ..voice.gnani import GnaniClient, GnaniSttStream

# Test and tooling routes. They spend Gnani credits, so they are for staff only: STT, TTS and
# the stream need the operator role. Participants speak through their own question routes.
router = APIRouter(prefix="/v1/voice", tags=["voice"])
Staff = Depends(require_staff())
Operator = Depends(require_staff(StaffRole.OPERATOR))

MAX_FRAME_BYTES = 64 * 1024


def _gnani(request: Request) -> GnaniClient:
    client: GnaniClient = request.app.state.gnani
    return client


@router.get("/status", dependencies=[Staff])
async def voice_status(request: Request) -> dict[str, object]:
    g = _gnani(request)
    return {
        "configured": g.configured,
        "stt_model": "prisma-v3.0",
        "tts_models": ["timbre-v3.0", "timbre-v2.5"],
        "base_url": g.base_url,
    }


@router.get("/usage", dependencies=[Staff])
async def voice_usage(request: Request) -> dict[str, object]:
    """Today's metered Gnani usage, the configured caps, and live limiter state."""
    g = _gnani(request)
    ledger = g.governor.ledger
    by_service = await ledger.by_service_today() if hasattr(ledger, "by_service_today") else {}
    return {
        "spent_today_inr": round(await ledger.spent_today(), 4),
        "by_service": by_service,
        **g.governor.status(),
    }


@router.post("/stt", dependencies=[Operator])
async def transcribe(
    request: Request,
    audio: Annotated[UploadFile, File()],
    language_codes: Annotated[str, Form()] = "hi-IN,en-IN",
    codemix: Annotated[bool, Form()] = False,
    keyterms: Annotated[str, Form()] = "",
) -> SttResult:
    limit: int = request.app.state.settings.voice_max_upload_bytes
    data = await audio.read(limit + 1)
    if len(data) > limit:
        raise ApiError(413, "VOICE_UPLOAD_TOO_LARGE", f"audio larger than {limit} bytes")
    if not data:
        raise ApiError(422, "VOICE_EMPTY_UPLOAD", "empty audio upload")
    codes = [c.strip() for c in language_codes.split(",") if c.strip()]
    terms = [t.strip() for t in keyterms.split(",") if t.strip()]
    return await _gnani(request).transcribe(
        data, audio.filename or "audio.wav", codes, codemix=codemix, keyterms=terms
    )


@router.post("/tts", dependencies=[Operator])
async def synthesize(request: Request, body: TtsRequest) -> Response:
    audio, wall_ms = await _gnani(request).synthesize(
        body.text, language=body.language, model=body.model, voice=body.voice, speed=body.speed
    )
    return Response(
        audio,
        media_type="audio/wav",
        headers={"X-TTS-Wall-Ms": f"{wall_ms:.0f}", "Cache-Control": "no-store"},
    )


@router.websocket("/stream")
async def stream(ws: WebSocket) -> None:
    """Protocol: client sends ``{"type":"start",...}``, then binary PCM16 16 kHz mono frames,
    optionally ``{"type":"commit"}``; ``{"type":"stop"}`` ends the session. Operators only:
    the handshake is refused (HTTP 403) before any Gnani session is opened."""
    try:
        await staff_on_socket(ws, StaffRole.OPERATOR)
    except ApiError:
        await ws.close(code=4401)
        return
    await ws.accept()
    gnani: GnaniClient = ws.app.state.gnani

    async def send(msg: MediaServerMessage) -> None:
        await ws.send_text(msg.model_dump_json(exclude_none=True))

    try:
        first = await asyncio.wait_for(ws.receive_text(), timeout=10)
        start = MediaClientMessage.model_validate_json(first)
        if start.type != "start":
            raise ValueError("first message must be start")
    except (TimeoutError, ValueError, ValidationError, WebSocketDisconnect, KeyError):
        await send(MediaServerMessage(type="error", message="expected a start message"))
        await ws.close(code=1008)
        return
    max_s: float = ws.app.state.settings.voice_max_stream_s
    try:
        async with gnani.stream(
            start.language_code or ["hi-IN", "en-IN"],
            codemix=start.codemix,
            keyterms=start.keyterms or (),
        ) as upstream:
            await send(MediaServerMessage(type="ready", model_confirmed=upstream.model_confirmed))
            await _pump(ws, upstream, send, max_s)
    except ApiError as exc:  # no slot, over budget, or Gnani refused the session
        await send(MediaServerMessage(type="error", message=f"{exc.code}: {exc.message}"))
    with contextlib.suppress(Exception):
        await send(MediaServerMessage(type="closed"))
        await ws.close()


async def _pump(ws: WebSocket, upstream: GnaniSttStream, send: Any, max_s: float) -> None:
    """Forward browser audio upstream until stop, disconnect, or the session time cap."""
    relay = asyncio.create_task(_relay_upstream(upstream, send))
    deadline = time.monotonic() + max_s
    try:
        while time.monotonic() < deadline and not relay.done():
            msg = await asyncio.wait_for(ws.receive(), timeout=deadline - time.monotonic())
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                chunk = msg["bytes"]
                if len(chunk) > MAX_FRAME_BYTES:
                    await send(MediaServerMessage(type="error", message="frame too large"))
                    break
                await upstream.send_pcm(chunk)
            elif msg.get("text") is not None:
                kind = json.loads(msg["text"]).get("type")
                if kind == "commit":
                    await upstream.commit()
                elif kind == "stop":
                    await upstream.commit()
                    await asyncio.wait_for(asyncio.shield(relay), timeout=5)
                    break
    except (TimeoutError, WebSocketDisconnect, json.JSONDecodeError):
        pass
    finally:
        relay.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await relay


async def _relay_upstream(upstream: GnaniSttStream, send: object) -> None:
    """Forward Prisma events; measure end-of-speech (``processing``) to transcript latency."""
    assert callable(send)
    speech_end: float | None = None
    async for ev in upstream.events():
        if ev.type == "speech_start":
            await send(MediaServerMessage(type="speech_start"))
        elif ev.type == "processing":
            speech_end = ev.received_at
            await send(MediaServerMessage(type="processing"))
        elif ev.type == "transcript":
            eos_ms = (ev.received_at - speech_end) * 1000 if speech_end else None
            speech_end = None
            latency = ev.raw.get("latency")
            await send(
                MediaServerMessage(
                    type="transcript",
                    text=str(ev.raw.get("text", "")),
                    detected_language=ev.raw.get("detected_language_code"),
                    provider_latency_ms=float(latency) if latency is not None else None,
                    end_of_speech_to_transcript_ms=eos_ms,
                )
            )
            log.info("stt_transcript", provider_latency_ms=latency, eos_ms=eos_ms)
        elif ev.type == "error":
            await send(MediaServerMessage(type="error", message=str(ev.raw.get("message", ""))))
        elif ev.type == "closed":
            await send(MediaServerMessage(type="closed", message=f"upstream {ev.raw.get('code')}"))
            return
