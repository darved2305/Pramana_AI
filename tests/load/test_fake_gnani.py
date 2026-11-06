"""Smoke tests for each Gnani surface used by the process-level load run."""

from __future__ import annotations

import io
import wave

from fastapi.testclient import TestClient
from voice_bot_common import encode_synthetic_pcm

from load.fake_gnani_server import FakeGnaniEmulator, create_app


def make_wav(pcm: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(pcm)
    return output.getvalue()


def test_fake_provider_covers_realtime_rest_and_both_tts_surfaces() -> None:
    emulator = FakeGnaniEmulator(seed=3, stt_delay_s=0, tts_chunk_delay_s=0)
    pcm = encode_synthetic_pcm("lights green hain")
    with TestClient(create_app(emulator)) as client:
        rest = client.post(
            "/stt/v3",
            data={"model": "prisma-v3.0", "language_code": "hi-IN,en-IN"},
            files={"audio_file": ("answer.wav", make_wav(pcm), "audio/wav")},
        )
        assert rest.status_code == 200
        assert rest.json()["transcript"] == "lights green hain"

        tts_body = {
            "text": "question",
            "model": "timbre-v3.0",
            "voice": "Shivani",
            "language": "en-IN",
            "speed": 1.0,
            "audio_config": {"sample_rate": 24000, "container": "wav"},
        }
        tts_rest = client.post("/api/v1/tts/inference", json=tts_body)
        assert tts_rest.status_code == 200
        assert tts_rest.content.startswith(b"RIFF")

        tts_stream = client.post("/api/v1/tts/sse", json=tts_body)
        assert tts_stream.status_code == 200
        assert "event: complete" in tts_stream.text

        with client.websocket_connect(
            "/stt/v3/stream",
            headers={"model": "prisma-v3.0", "language_code": "hi-IN", "X-API-Key-ID": "test"},
        ) as ws:
            assert ws.receive_json()["type"] == "connected"
            for offset in range(0, len(pcm), 1024):
                ws.send_bytes(pcm[offset : offset + 1024])
            assert ws.receive_json()["type"] == "speech_start"
            ws.send_text('{"type":"commit"}')
            assert ws.receive_json()["type"] == "processing"
            transcript = ws.receive_json()
            assert transcript["type"] == "transcript"
            assert transcript["text"] == "lights green hain"

    metrics = emulator.snapshot()
    assert metrics["stt_rest_requests"] == 1
    assert metrics["tts_rest_requests"] == 1
    assert metrics["tts_sse_requests"] == 1
    assert metrics["websocket_sessions_opened"] == 1
    assert metrics["websocket_sessions_closed"] == 1
    assert metrics["websocket_close_events"][0]["code"] == 1000
