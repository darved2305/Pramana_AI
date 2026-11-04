"""Voice contracts: call states, speech results, and the media WebSocket protocol."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from .common import LanguageCode, StrictModel


class CallState(StrEnum):
    """Per-call state machine (PLAN.md §12)."""

    RINGING = "ringing"
    CONSENT = "consent"
    ASKING = "asking"
    LISTENING = "listening"
    EXTRACTING = "extracting"
    IDLE = "idle"
    CLOSING = "closing"
    ENDED = "ended"
    UNAVAILABLE = "unavailable"


class SttResult(StrictModel):
    transcript: str
    detected_language: str | None
    model: str | None
    """Model reported by Gnani (REST) or the model we requested (streaming)."""
    provider_request_id: str | None
    provider_latency_ms: float | None
    """Latency reported by Gnani (REST ``processing_time`` or stream ``latency``)."""
    wall_ms: float
    """Our measured wall-clock time for the whole request."""
    audio_ms: float | None = None
    empty: bool


class TtsRequest(StrictModel):
    text: str = Field(min_length=1, max_length=600)
    language: LanguageCode | Literal["hi-en"] = "en-IN"
    model: Literal["timbre-v3.0", "timbre-v2.5"] = "timbre-v3.0"
    voice: str | None = None
    """Defaults per model/language are chosen server-side."""
    speed: float = Field(default=1.0, ge=0.85, le=1.15)


class MediaClientMessage(StrictModel):
    """JSON control frames from the browser on ``/v1/voice/stream``."""

    type: Literal["start", "stop", "commit"]
    language_code: list[LanguageCode] | None = None
    keyterms: list[str] | None = None
    codemix: bool = False


class MediaServerMessage(StrictModel):
    """JSON frames sent to the browser on ``/v1/voice/stream``."""

    type: Literal["ready", "speech_start", "processing", "transcript", "error", "closed"]
    text: str | None = None
    detected_language: str | None = None
    provider_latency_ms: float | None = None
    end_of_speech_to_transcript_ms: float | None = None
    message: str | None = None
    model_confirmed: bool | None = None
