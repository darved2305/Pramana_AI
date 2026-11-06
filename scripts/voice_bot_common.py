"""Shared participants and audio helpers for the live and emulated voice bots."""

from __future__ import annotations

import base64
import json
import math
import sys
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

PEOPLE = [
    {
        "id": "p_riya",
        "display_name": "Riya",
        "roles": ["student"],
        "skill": "lay",
        "location_id": "F3_R304",
        "languages": {
            "stt_candidates": ["hi-IN", "en-IN"],
            "template_language": "hi-en",
            "codemix": True,
        },
    },
    {
        "id": "p_mahesh",
        "display_name": "Mahesh",
        "roles": ["guard"],
        "skill": "access",
        "location_id": "GUARD_DESK",
        "languages": {"stt_candidates": ["mr-IN", "hi-IN"], "template_language": "mr"},
    },
    {
        "id": "p_imran",
        "display_name": "Imran",
        "roles": ["electrician"],
        "skill": "technician",
        "location_id": "MAINT_ROOM",
        "languages": {"stt_candidates": ["hi-IN"], "template_language": "hi"},
    },
]
CLIP_LANG = {"hi-en": "hi", "hi": "hi", "mr": "mr", "en": "hi"}
DONE = {"decided", "abstained", "verified", "not_verified", "closed"}
FRAME = 1024

_SYNTHETIC_MARKER = b"\x00P3-LOAD-AUDIO\x00"
_SYNTHETIC_MIN_BYTES = 6144


class CallSocketMetrics:
    """Track participant call sockets and time spent with three open at once."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._active: set[str] = set()
        self._opened = 0
        self._closed = 0
        self._peak_open = 0
        self._three_way_seconds = 0.0
        self._last_change = clock()

    def _advance(self) -> None:
        now = self._clock()
        if len(self._active) >= 3:
            self._three_way_seconds += max(0.0, now - self._last_change)
        self._last_change = now

    def opened(self, participant_id: str) -> None:
        self._advance()
        if participant_id in self._active:
            raise RuntimeError(f"participant {participant_id} already has an open call socket")
        self._active.add(participant_id)
        self._opened += 1
        self._peak_open = max(self._peak_open, len(self._active))

    def closed(self, participant_id: str) -> None:
        self._advance()
        if participant_id not in self._active:
            raise RuntimeError(f"participant {participant_id} has no open call socket")
        self._active.remove(participant_id)
        self._closed += 1

    def snapshot(self) -> dict[str, int | float]:
        self._advance()
        return {
            "opened": self._opened,
            "closed": self._closed,
            "peak_open": self._peak_open,
            "active": len(self._active),
            "three_way_seconds": round(self._three_way_seconds, 3),
        }


def latency_percentiles_ms(values: list[float]) -> dict[str, float | int | None]:
    """Return interpolated caller-side latency percentiles and their sample count."""
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return {"p50_ms": None, "p95_ms": None, "sample_count": 0}

    def at(probability: float) -> float:
        position = (len(ordered) - 1) * probability
        lower = math.floor(position)
        upper = math.ceil(position)
        fraction = position - lower
        return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction

    return {
        "p50_ms": at(0.5),
        "p95_ms": at(0.95),
        "sample_count": len(ordered),
    }


def join_segment(payload: dict[str, str]) -> str:
    """Encode a participant link segment using the web client's compact JSON format."""
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def pcm(path: Path) -> bytes:
    """Read a 16 kHz mono PCM16 voice clip."""
    with wave.open(str(path)) as wav_file:
        if (wav_file.getframerate(), wav_file.getnchannels(), wav_file.getsampwidth()) != (
            16000,
            1,
            2,
        ):
            sys.exit(f"{path.name}: clips must be 16 kHz mono PCM16")
        return wav_file.readframes(wav_file.getnframes())


def waiting(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Return every question currently in flight."""
    questions = state.get("pending_questions")
    if questions:
        return list(questions)
    return [state["pending_question"]] if state.get("pending_question") else []


def mine(state: dict[str, Any], participant_id: str) -> dict[str, Any] | None:
    return next(
        (
            question
            for question in waiting(state)
            if question["action"]["participant_id"] == participant_id
        ),
        None,
    )


def encode_synthetic_pcm(text: str) -> bytes:
    """Put test-only text in a deterministic, frame-aligned PCM16 carrier.

    These bytes are synthetic input for the local provider emulator. They are not speech audio
    and must never be sent to a live provider.
    """
    payload = text.encode("utf-8")
    if len(payload) > 65535:
        raise ValueError("synthetic transcript is too long")
    carrier = _SYNTHETIC_MARKER + len(payload).to_bytes(2, "little") + payload
    padded_length = max(_SYNTHETIC_MIN_BYTES, ((len(carrier) + FRAME - 1) // FRAME) * FRAME)
    padded_length = ((padded_length + FRAME - 1) // FRAME) * FRAME
    return carrier.ljust(padded_length, b"\x00")


def decode_synthetic_pcm(pcm_data: bytes) -> str:
    """Decode the test-only transcript carrier embedded in PCM16 bytes."""
    marker = pcm_data.find(_SYNTHETIC_MARKER)
    if marker < 0:
        raise ValueError("audio does not contain the load-test marker")
    size_start = marker + len(_SYNTHETIC_MARKER)
    size_end = size_start + 2
    if len(pcm_data) < size_end:
        raise ValueError("synthetic transcript length is incomplete")
    size = int.from_bytes(pcm_data[size_start:size_end], "little")
    end = size_end + size
    if len(pcm_data) < end:
        raise ValueError("synthetic transcript payload is incomplete")
    try:
        return pcm_data[size_end:end].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("synthetic transcript is not UTF-8") from exc


def transcript_for_value(value: str) -> str:
    """Use short words that the existing rules extractor recognizes for each observation."""
    return {
        "no_network": "no network",
        "stuck_connecting": "stuck connecting",
    }.get(value, value)
