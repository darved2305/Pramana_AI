"""The load bot's test-only PCM marker is stable and survives WAV wrapping."""

from __future__ import annotations

import io
import wave

import pytest
from voice_bot_common import decode_synthetic_pcm, encode_synthetic_pcm


def test_test_audio_round_trips_deterministically() -> None:
    transcript = "lights green hain"
    first = encode_synthetic_pcm(transcript)
    second = encode_synthetic_pcm(transcript)

    assert first == second
    assert len(first) >= 3200
    assert len(first) % 2 == 0
    assert decode_synthetic_pcm(first) == transcript

    wrapped = io.BytesIO()
    with wave.open(wrapped, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(first)
    assert decode_synthetic_pcm(wrapped.getvalue()) == transcript


def test_test_audio_rejects_an_incomplete_marker() -> None:
    audio = b"\x00P3-LOAD-AUDIO\x00\x02"

    with pytest.raises(ValueError, match="incomplete"):
        decode_synthetic_pcm(audio)
