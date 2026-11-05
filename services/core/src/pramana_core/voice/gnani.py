"""Gnani Vachana speech adapters: Prisma STT (REST and realtime WebSocket) and Timbre TTS (REST).

Wire formats were verified on 2026-11-04 against docs.gnani.ai (STT realtime, Prisma v3, errors,
limits, TTS pages) and against the source of ``gnani-vachana`` 0.9.0, ``livekit-plugins-gnani``
1.8.10 and ``pipecat-gnani`` 0.6.0. See docs/engineering/GNANI_INTEGRATION.md. Key facts:

* REST STT ``POST /stt/v3`` multipart: ``audio_file``, ``model``, ``language_code`` (``indic-auto``
  or 1-4 comma-separated codes on prisma-v3.0), ``format``, ``keyterms``, ``topic``,
  ``previous_text``; header ``X-API-Key-ID``; audio <= 30 s.
* Realtime STT ``wss://.../stt/v3/stream``: headers use the REST names (``language_code``,
  ``model``, ``format``, ``keyterms``); legacy ``lang_code``/``x-model`` are still accepted.
  An unknown model value is silently ignored (v2.5 is used), so we check the ``connected``
  echo for the v3.0 config shape. Binary frames must be exactly 1,024 bytes of PCM s16le mono
  sent at real-time cadence. Transcripts are final-only; there are no confidence scores.
* Errors: 401 auth, 402 insufficient credit, 403 scope, 429 rate limit (no Retry-After),
  504 upstream timeout. Retry only 429/5xx/connection errors with 0.5/1/2 s backoff.
* TTS REST ``POST /api/v1/tts/inference`` JSON ``{text, model, voice, language, speed,
  audio_config}`` returns the whole audio file.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import struct
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
import websockets
from websockets.asyncio.client import ClientConnection

from pramana_contracts import SttResult

from ..errors import ApiError
from ..observability import log
from .governor import GovernorLimits, MemoryLedger, VoiceGovernor, stt_cost, tts_cost

FRAME_BYTES = 1024
SAMPLE_RATE = 16_000
PRISMA_V3 = "prisma-v3.0"
RETRY_BACKOFF_S = (0.5, 1.0, 2.0)
MAX_REST_AUDIO_S = 30.0

# Default Timbre voices. v3.0 voices speak all ten languages; Hinglish (hi-en) exists only on
# v2.5 (voice Poorvi). Choices are provisional until a native-speaker listening test.
DEFAULT_VOICES = {"timbre-v3.0": "Shivani", "timbre-v2.5": "Nalini"}
V25_LANGUAGE_VOICES = {"mr-IN": "Zahira", "hi-en": "Poorvi", "en-IN": "Kaveri", "hi-IN": "Nalini"}


class VoiceError(ApiError):
    pass


def _error_for(status: int, body: str) -> VoiceError:
    detail = body[:300]
    if status in (401,):
        return VoiceError(502, "VOICE_AUTH_FAILED", "Gnani rejected the API key")
    if status == 402:
        return VoiceError(502, "VOICE_CREDIT_EXHAUSTED", "Gnani credits exhausted")
    if status == 403:
        return VoiceError(502, "VOICE_SCOPE_DENIED", f"Gnani scope denied: {detail}")
    if status == 429:
        return VoiceError(503, "VOICE_RATE_LIMITED", "Gnani rate limit reached")
    if status == 504:
        return VoiceError(504, "VOICE_PROVIDER_TIMEOUT", "Gnani upstream timeout")
    if status >= 500:
        return VoiceError(502, "VOICE_PROVIDER_ERROR", f"Gnani error {status}")
    return VoiceError(422, "VOICE_REQUEST_REJECTED", f"Gnani rejected the request: {detail}")


def wav_duration_s(data: bytes) -> float | None:
    """Duration of a PCM WAV file from its header, or None if it is not a parsable WAV."""
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return None
    pos, byte_rate, data_len = 12, None, None
    while pos + 8 <= len(data):
        chunk_id, size = data[pos : pos + 4], struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        if chunk_id == b"fmt " and size >= 16:
            byte_rate = struct.unpack("<I", data[pos + 16 : pos + 20])[0]
        elif chunk_id == b"data":
            data_len = min(size, len(data) - pos - 8)
            break
        pos += 8 + size + (size & 1)
    if not byte_rate or data_len is None:
        return None
    return float(data_len) / float(byte_rate)


def language_header(codes: Sequence[str]) -> str:
    if not 1 <= len(codes) <= 4:
        raise VoiceError(422, "VOICE_BAD_LANGUAGES", "give 1-4 language codes")
    return ",".join(codes)


@dataclass
class SttStreamEvent:
    type: str
    raw: dict[str, Any]
    received_at: float


class GnaniSttStream:
    """One realtime Prisma session. Owned by a single task; not shared between calls."""

    def __init__(self, ws: ClientConnection, connected: dict[str, Any], expect_v3: bool) -> None:
        self._ws = ws
        self.connected = connected
        cfg = connected.get("config") or {}
        # v3.0 sessions echo language_code/format; v2.5 (the silent fallback) does not.
        self.model_confirmed = (not expect_v3) or ("language_code" in cfg)
        self._pending = bytearray()
        self._bytes_sent = 0

    @property
    def audio_seconds_sent(self) -> float:
        """Billable audio actually streamed to Gnani (16 kHz, 16-bit mono)."""
        return self._bytes_sent / (2 * SAMPLE_RATE)

    async def _send_frame(self, frame: bytes) -> None:
        await self._ws.send(frame)
        self._bytes_sent += len(frame)

    async def send_pcm(self, pcm: bytes) -> None:
        """Buffer arbitrary PCM and send exact 1,024-byte frames (protocol requirement)."""
        self._pending.extend(pcm)
        while len(self._pending) >= FRAME_BYTES:
            frame = bytes(self._pending[:FRAME_BYTES])
            del self._pending[:FRAME_BYTES]
            await self._send_frame(frame)

    async def commit(self) -> None:
        """Flush a final partial frame (zero-padded) and close the open utterance now."""
        if self._pending:
            await self._send_frame(bytes(self._pending).ljust(FRAME_BYTES, b"\x00"))
            self._pending.clear()
        await self._ws.send(json.dumps({"type": "commit"}))

    async def events(self) -> AsyncIterator[SttStreamEvent]:
        try:
            async for msg in self._ws:
                if isinstance(msg, bytes):
                    continue
                try:
                    payload = json.loads(msg)
                except json.JSONDecodeError:
                    continue
                yield SttStreamEvent(str(payload.get("type", "")), payload, time.perf_counter())
        except websockets.ConnectionClosed as exc:
            code = exc.rcvd.code if exc.rcvd else None
            yield SttStreamEvent(
                "closed",
                {"code": code, "reason": exc.rcvd.reason if exc.rcvd else ""},
                time.perf_counter(),
            )
            return
        # websockets ends iteration silently on 1000/1001 ("OK" closures), so read the real
        # code: 1001 is Gnani's 15-minute session cap and must not look like a normal close.
        yield SttStreamEvent(
            "closed",
            {"code": self._ws.close_code, "reason": self._ws.close_reason or ""},
            time.perf_counter(),
        )

    async def aclose(self) -> None:
        """Start closing and return at once. Gnani takes about a second to complete the close
        handshake, and nothing depends on it: the next question should not wait for it."""
        task = asyncio.create_task(_close_quietly(self._ws))
        _CLOSING.add(task)
        task.add_done_callback(_CLOSING.discard)


_CLOSING: set[asyncio.Task[None]] = set()
"""Close handshakes in progress (kept referenced so they are not garbage-collected)."""
CLOSE_TIMEOUT_S = 3.0


async def _close_quietly(ws: ClientConnection) -> None:
    with contextlib.suppress(Exception):
        await asyncio.wait_for(ws.close(), CLOSE_TIMEOUT_S)


class GnaniClient:
    def __init__(
        self,
        api_key: str | None,
        base_url: str,
        timeout_s: float,
        governor: VoiceGovernor | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._key = api_key
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout_s
        # Every call goes through a governor; tests get conservative in-memory defaults.
        self.governor = governor or VoiceGovernor(GovernorLimits(), MemoryLedger())
        self._http = httpx.AsyncClient(
            base_url=self.base_url, timeout=httpx.Timeout(timeout_s), transport=transport
        )

    @property
    def configured(self) -> bool:
        return bool(self._key)

    def _require_key(self) -> str:
        if not self._key:
            raise VoiceError(503, "VOICE_NOT_CONFIGURED", "GNANI_API_KEY is not configured")
        return self._key

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, service: str, **kwargs: Any) -> httpx.Response:
        key = self._require_key()
        headers = {
            "X-API-Key-ID": key,
            "X-API-Request-ID": uuid.uuid4().hex,
            **kwargs.pop("headers", {}),
        }
        last: VoiceError | None = None
        for attempt, backoff in enumerate((*RETRY_BACKOFF_S, None)):
            await self.governor.pace(service)  # every attempt counts against the per-minute cap
            try:
                resp = await self._http.request(method, path, headers=headers, **kwargs)
            except httpx.TimeoutException:
                last = VoiceError(504, "VOICE_TIMEOUT", "Gnani request timed out")
            except httpx.HTTPError as exc:
                last = VoiceError(
                    502, "VOICE_UNREACHABLE", f"Gnani unreachable: {type(exc).__name__}"
                )
            else:
                if resp.status_code < 400:
                    return resp
                last = _error_for(resp.status_code, resp.text)
                if resp.status_code != 429 and resp.status_code < 500:
                    raise last
            log.warning("gnani_retry", path=path, attempt=attempt, code=last.code)
            if backoff is None:
                break
            await asyncio.sleep(backoff)
        assert last is not None
        raise last

    async def transcribe(
        self,
        audio: bytes,
        filename: str,
        language_codes: Sequence[str],
        *,
        model: str = PRISMA_V3,
        codemix: bool = False,
        keyterms: Sequence[str] = (),
        topic: str | None = None,
        previous_text: str | None = None,
    ) -> SttResult:
        """REST transcription of one utterance (<= 30 s)."""
        duration = wav_duration_s(audio) if filename.lower().endswith(".wav") else None
        if filename.lower().endswith(".wav") and duration is None:
            raise VoiceError(422, "VOICE_INVALID_AUDIO", "not a valid PCM WAV file")
        if duration is not None and duration > MAX_REST_AUDIO_S:
            raise VoiceError(413, "VOICE_AUDIO_TOO_LONG", "audio longer than 30 s")
        data: dict[str, str] = {"model": model, "language_code": language_header(language_codes)}
        if codemix:
            data["format"] = "codemix"
        if keyterms:
            data["keyterms"] = json.dumps(list(keyterms)[:200], ensure_ascii=False)
        if topic:
            data["topic"] = topic[:1600]
        if previous_text:
            data["previous_text"] = previous_text[-600:]
        self._require_key()
        # Non-WAV durations are unknown before upload: price the 30 s maximum, bill it too.
        billable_s = duration if duration is not None else MAX_REST_AUDIO_S
        async with self.governor.rest_call("stt_rest", billable_s, stt_cost(billable_s)):
            start = time.perf_counter()
            resp = await self._request(
                "POST", "/stt/v3", "stt_rest", data=data, files={"audio_file": (filename, audio)}
            )
            wall_ms = (time.perf_counter() - start) * 1000
        body = resp.json()
        if not body.get("success", False):
            err = body.get("error") or {}
            raise VoiceError(502, "VOICE_PROVIDER_ERROR", str(err.get("type", "unknown")))
        transcript = str(body.get("transcript", ""))
        processing = body.get("processing_time")
        return SttResult(
            transcript=transcript,
            detected_language=body.get("detected_language_code"),
            model=body.get("model"),
            provider_request_id=body.get("request_id"),
            provider_latency_ms=float(processing) * 1000 if processing is not None else None,
            wall_ms=wall_ms,
            audio_ms=duration * 1000 if duration is not None else None,
            empty=not transcript.strip(),
        )

    async def synthesize(
        self,
        text: str,
        *,
        language: str,
        model: str = "timbre-v3.0",
        voice: str | None = None,
        speed: float = 1.0,
        sample_rate: int = 24_000,
    ) -> tuple[bytes, float]:
        """Return (WAV bytes, wall-clock ms). Hinglish (hi-en) is routed to timbre-v2.5."""
        if language == "hi-en":
            model = "timbre-v2.5"
        if voice is None:
            voice = (
                V25_LANGUAGE_VOICES.get(language) if model == "timbre-v2.5" else None
            ) or DEFAULT_VOICES[model]
        body = {
            "text": text,
            "model": model,
            "voice": voice,
            "language": language,
            "speed": speed,
            "audio_config": {
                "sample_rate": sample_rate,
                "num_channels": 1,
                "sample_width": 2,
                "encoding": "linear_pcm",
                "container": "wav",
            },
        }
        self._require_key()
        chars = len(text)  # audio tags are billable characters too
        async with self.governor.rest_call("tts", chars, tts_cost(chars)):
            start = time.perf_counter()
            resp = await self._request("POST", "/api/v1/tts/inference", "tts", json=body)
            wall_ms = (time.perf_counter() - start) * 1000
        audio = resp.content
        if not audio:
            raise VoiceError(502, "VOICE_EMPTY_AUDIO", "Gnani returned no audio")
        if audio[:4] != b"RIFF":
            raise VoiceError(
                502,
                "VOICE_UNEXPECTED_AUDIO",
                f"expected WAV, got {resp.headers.get('content-type')}",
            )
        return audio, wall_ms

    @asynccontextmanager
    async def stream(
        self, language_codes: Sequence[str], **kwargs: Any
    ) -> AsyncIterator[GnaniSttStream]:
        """A realtime session holding one of the account's concurrent-session slots.

        Billable seconds are metered from the audio actually sent; the upstream session is
        closed when the block exits, however it exits.
        """
        self._require_key()
        async with self.governor.stream_slot() as usage:
            usage[1] = 1.0  # the session attempt reaches Gnani from here on
            upstream = await self.open_stream(language_codes, **kwargs)
            try:
                yield upstream
            finally:
                usage[0] = upstream.audio_seconds_sent
                await upstream.aclose()

    async def open_stream(
        self,
        language_codes: Sequence[str],
        *,
        model: str = PRISMA_V3,
        codemix: bool = False,
        keyterms: Sequence[str] = (),
        topic: str | None = None,
        min_silence_ms: int = 600,
        min_segment_ms: int = 100,
        idle_timeout_s: int = 60,
    ) -> GnaniSttStream:
        """Open a realtime session with per-question context headers."""
        key = self._require_key()
        headers = {
            "x-api-key-id": key,
            "x-api-request-id": uuid.uuid4().hex,
            "model": model,
            "x-model": model,
            "x-sample-rate": str(SAMPLE_RATE),
            "x-min-silence-ms": str(min_silence_ms),
            "x-min-segment-ms": str(min_segment_ms),  # higher values drop short "yes"/"no"
            "x-idle-timeout-sec": str(idle_timeout_s),
            "format": "codemix" if codemix else "verbatim",
            "x-format": "codemix" if codemix else "verbatim",
        }
        # Verified live on 2026-11-04: the streaming server rejects a comma list in
        # language_code ("exactly one locale is required"), contrary to the docs page. Several
        # candidates go as language_code=indic-auto plus x-language-candidates, the shape the
        # official SDK (gnani-vachana 0.9.0) sends. Legacy and canonical names carry the same
        # values so whichever the server reads, it reads the same thing.
        langs = language_header(language_codes).split(",")
        lang_code = langs[0] if len(langs) == 1 else "indic-auto"
        headers["language_code"] = headers["lang_code"] = lang_code
        if len(langs) > 1:
            headers["x-language-candidates"] = ",".join(langs)
        if keyterms:
            terms = json.dumps(list(keyterms)[:200])  # JSON-escaped: header values must be ASCII
            headers["keyterms"] = headers["x-keywords"] = terms
        if topic:
            headers["topic"] = topic.encode("ascii", "ignore").decode()[:1600]
        url = self.base_url.replace("https://", "wss://").replace("http://", "ws://")
        url += "/stt/v3/stream"
        try:
            ws = await asyncio.wait_for(
                websockets.connect(
                    url,
                    additional_headers=headers,
                    ping_interval=20,
                    ping_timeout=20,
                    close_timeout=5,
                    max_size=2**20,
                ),
                timeout=self._timeout,
            )
        except websockets.InvalidStatus as exc:
            raise _error_for(
                exc.response.status_code,
                exc.response.body.decode(errors="replace") if exc.response.body else "",
            ) from exc
        except (TimeoutError, OSError, websockets.WebSocketException) as exc:
            raise VoiceError(
                502, "VOICE_UNREACHABLE", f"cannot open STT stream: {type(exc).__name__}"
            ) from exc
        try:
            first = json.loads(await asyncio.wait_for(ws.recv(), timeout=self._timeout))
        except Exception as exc:
            await ws.close()
            raise VoiceError(502, "VOICE_STREAM_FAILED", "no connected message") from exc
        if first.get("type") != "connected":
            await ws.close()
            raise VoiceError(
                502, "VOICE_STREAM_FAILED", str(first.get("message", "unexpected first message"))
            )
        stream = GnaniSttStream(ws, first, expect_v3=(model == PRISMA_V3))
        if not stream.model_confirmed:
            log.warning("gnani_model_not_confirmed", requested=model)
        return stream
