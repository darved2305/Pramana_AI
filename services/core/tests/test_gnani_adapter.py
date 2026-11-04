"""Gnani adapter tests against protocol emulations (no network, no credits).

REST calls use ``httpx.MockTransport``; realtime uses ``fake_gnani.FakeGnani``. Live calls are in
``tests/live/test_gnani_live.py`` and need GNANI_API_KEY.
"""

from __future__ import annotations

import io
import json
import struct
import wave
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from core_testkit import core_settings
from fake_gnani import FakeGnani
from fastapi.testclient import TestClient

from pramana_core.main import create_app
from pramana_core.voice import gnani as gmod
from pramana_core.voice.gnani import GnaniClient, VoiceError, wav_duration_s


def wav(seconds: float, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gmod, "RETRY_BACKOFF_S", (0.0, 0.0, 0.0))


def client(handler: Any, key: str | None = "k") -> GnaniClient:
    return GnaniClient(key, "https://api.vachana.ai", 5, transport=httpx.MockTransport(handler))


def test_wav_duration() -> None:
    assert wav_duration_s(wav(1.5)) == pytest.approx(1.5)
    assert wav_duration_s(b"not a wav") is None


async def test_rest_transcription_sends_documented_fields() -> None:
    seen: dict[str, Any] = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["path"] = req.url.path
        seen["key"] = req.headers["X-API-Key-ID"]
        seen["body"] = req.content
        return httpx.Response(
            200,
            json={
                "success": True,
                "request_id": "r1",
                "transcript": "बंद आहे",
                "model": "prisma-v3.0",
                "detected_language_code": "mr-IN",
                "processing_time": 0.31,
                "end_to_end_latency": 0.4,
            },
        )

    g = client(handler)
    r = await g.transcribe(
        wav(1.0), "a.wav", ["mr-IN", "hi-IN"], codemix=True, keyterms=["NAVA-WiFi", "बंद"]
    )
    assert seen["path"] == "/stt/v3"
    assert seen["key"] == "k"
    body = seen["body"].decode("utf-8", "replace")
    for field, value in [
        ("model", "prisma-v3.0"),
        ("language_code", "mr-IN,hi-IN"),
        ("format", "codemix"),
    ]:
        assert f'name="{field}"\r\n\r\n{value}' in body
    assert '["NAVA-WiFi", "बंद"]' in body
    assert r.transcript == "बंद आहे"
    assert r.model == "prisma-v3.0"
    assert r.detected_language == "mr-IN"
    assert r.provider_latency_ms == pytest.approx(310)
    assert r.audio_ms == pytest.approx(1000)
    assert not r.empty
    await g.aclose()


async def test_empty_transcript_is_reported_not_raised() -> None:
    g = client(
        lambda _: httpx.Response(200, json={"success": True, "request_id": "r", "transcript": ""})
    )
    r = await g.transcribe(wav(0.05), "a.wav", ["hi-IN"])
    assert r.empty
    await g.aclose()


@pytest.mark.parametrize(
    ("status", "code", "calls"),
    [
        (401, "VOICE_AUTH_FAILED", 1),
        (402, "VOICE_CREDIT_EXHAUSTED", 1),
        (403, "VOICE_SCOPE_DENIED", 1),
        (400, "VOICE_REQUEST_REJECTED", 1),
        (429, "VOICE_RATE_LIMITED", 4),
        (504, "VOICE_PROVIDER_TIMEOUT", 4),
        (500, "VOICE_PROVIDER_ERROR", 4),
    ],
)
async def test_errors_are_typed_and_only_transient_ones_retried(
    status: int, code: str, calls: int
) -> None:
    n = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal n
        n += 1
        return httpx.Response(status, json={"detail": {"error_code": "X"}})

    g = client(handler)
    with pytest.raises(VoiceError) as exc:
        await g.transcribe(wav(1), "a.wav", ["hi-IN"])
    assert exc.value.code == code
    assert n == calls
    await g.aclose()


async def test_rate_limit_then_success_recovers() -> None:
    replies = iter(
        [
            httpx.Response(429),
            httpx.Response(200, json={"success": True, "request_id": "r", "transcript": "haan"}),
        ]
    )
    g = client(lambda _: next(replies))
    assert (await g.transcribe(wav(1), "a.wav", ["hi-IN"])).transcript == "haan"
    await g.aclose()


async def test_timeouts_are_typed() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    g = client(handler)
    with pytest.raises(VoiceError) as exc:
        await g.transcribe(wav(1), "a.wav", ["hi-IN"])
    assert exc.value.code == "VOICE_TIMEOUT"
    await g.aclose()


@pytest.mark.parametrize(
    ("audio", "code"),
    [(b"RIFF....garbage", "VOICE_INVALID_AUDIO"), (wav(31), "VOICE_AUDIO_TOO_LONG")],
)
async def test_bad_audio_is_rejected_before_spending_credits(audio: bytes, code: str) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call Gnani")

    g = client(handler)
    with pytest.raises(VoiceError) as exc:
        await g.transcribe(audio, "a.wav", ["hi-IN"])
    assert exc.value.code == code
    await g.aclose()


async def test_unconfigured_client_refuses() -> None:
    g = client(lambda _: httpx.Response(200), key=None)
    with pytest.raises(VoiceError) as exc:
        await g.synthesize("hello", language="en-IN")
    assert exc.value.code == "VOICE_NOT_CONFIGURED"
    await g.aclose()


async def test_tts_request_and_hinglish_routing() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return httpx.Response(200, content=wav(0.5, 24000), headers={"content-type": "audio/wav"})

    g = client(handler)
    audio, _ = await g.synthesize("तुम्ही बघा", language="mr-IN")
    assert audio[:4] == b"RIFF"
    assert bodies[0]["model"] == "timbre-v3.0"
    assert bodies[0]["voice"] == "Shivani"
    assert bodies[0]["audio_config"] == {
        "sample_rate": 24000,
        "num_channels": 1,
        "sample_width": 2,
        "encoding": "linear_pcm",
        "container": "wav",
    }
    await g.synthesize("WiFi dikh raha hai?", language="hi-en")
    assert (bodies[1]["model"], bodies[1]["voice"]) == ("timbre-v2.5", "Poorvi")
    await g.aclose()


@pytest.mark.parametrize("content", [b"", b"ID3mp3data"])
async def test_tts_rejects_empty_or_unexpected_audio(content: bytes) -> None:
    g = client(lambda _: httpx.Response(200, content=content))
    with pytest.raises(VoiceError):
        await g.synthesize("hello", language="en-IN")
    await g.aclose()


@pytest.fixture
def fake() -> Iterator[FakeGnani]:
    server = FakeGnani().start()
    yield server
    server.stop()


async def test_stream_headers_frames_and_transcript(fake: FakeGnani) -> None:
    g = GnaniClient("k", fake.base_url, 5)
    stream = await g.open_stream(["mr-IN", "hi-IN"], keyterms=["NAVA-WiFi", "बंद"])
    h = fake.seen_headers[-1]
    assert h["x-api-key-id"] == "k"
    assert h["model"] == "prisma-v3.0"
    assert h["language_code"] == "mr-IN,hi-IN"
    assert h["x-sample-rate"] == "16000"
    assert h["x-min-segment-ms"] == "100"
    assert json.loads(h["keyterms"]) == ["NAVA-WiFi", "बंद"]
    assert h["keyterms"].isascii()
    assert stream.model_confirmed
    pcm = struct.pack("<h", 1000) * 1300  # 2,600 bytes: not a multiple of 1,024
    await stream.send_pcm(pcm[:1000])
    await stream.send_pcm(pcm[1000:])
    await stream.commit()
    events = []
    async for ev in stream.events():
        events.append(ev)
        if ev.type == "transcript":
            break
    await stream.aclose()
    assert [e.type for e in events] == ["speech_start", "processing", "transcript"]
    assert events[-1].raw["text"] == "बंद आहे"
    assert fake.frame_sizes == [1024, 1024, 1024]  # two full frames + one zero-padded tail
    await g.aclose()


async def test_silent_model_fallback_is_detected() -> None:
    fake = FakeGnani(confirm_v3=False).start()
    g = GnaniClient("k", fake.base_url, 5)
    stream = await g.open_stream(["hi-IN"])
    assert stream.model_confirmed is False
    await stream.aclose()
    await g.aclose()
    fake.stop()


@pytest.mark.parametrize(
    ("status", "code"), [(401, "VOICE_AUTH_FAILED"), (429, "VOICE_RATE_LIMITED")]
)
async def test_stream_handshake_rejection(status: int, code: str) -> None:
    fake = FakeGnani(reject_status=status).start()
    g = GnaniClient("k", fake.base_url, 5)
    with pytest.raises(VoiceError) as exc:
        await g.open_stream(["hi-IN"])
    assert exc.value.code == code
    await g.aclose()
    fake.stop()


async def test_session_limit_close_is_surfaced() -> None:
    fake = FakeGnani(close_code=1001).start()
    g = GnaniClient("k", fake.base_url, 5)
    stream = await g.open_stream(["hi-IN"])
    events = [ev async for ev in stream.events()]
    assert events[-1].type == "closed"
    assert events[-1].raw["code"] == 1001
    await g.aclose()
    fake.stop()


def test_browser_stream_relay_end_to_end(fake: FakeGnani, migrated_db: str) -> None:
    app = create_app(core_settings(migrated_db, GNANI_API_KEY="k", GNANI_BASE_URL=fake.base_url))
    with TestClient(app) as c, c.websocket_connect("/v1/voice/stream") as ws:
        ws.send_text(json.dumps({"type": "start", "language_code": ["mr-IN", "hi-IN"]}))
        assert json.loads(ws.receive_text()) == {"type": "ready", "model_confirmed": True}
        ws.send_bytes(b"\x01\x00" * 600)
        ws.send_text(json.dumps({"type": "commit"}))
        seen = []
        while True:
            msg = json.loads(ws.receive_text())
            seen.append(msg["type"])
            if msg["type"] == "transcript":
                break
        assert msg["text"] == "बंद आहे"
        assert msg["provider_latency_ms"] == 320
        assert msg["end_of_speech_to_transcript_ms"] >= 0
        assert seen == ["speech_start", "processing", "transcript"]


def test_browser_stream_requires_start_message(migrated_db: str) -> None:
    app = create_app(core_settings(migrated_db, GNANI_API_KEY="k"))
    with TestClient(app) as c, c.websocket_connect("/v1/voice/stream") as ws:
        ws.send_text(json.dumps({"type": "commit"}))
        assert json.loads(ws.receive_text())["type"] == "error"


def test_voice_routes_without_key(migrated_db: str) -> None:
    app = create_app(core_settings(migrated_db))
    with TestClient(app) as c:
        assert c.get("/v1/voice/status").json()["configured"] is False
        r = c.post("/v1/voice/tts", json={"text": "hello"})
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "VOICE_NOT_CONFIGURED"
        r = c.post("/v1/voice/stt", files={"audio": ("a.wav", wav(1), "audio/wav")})
        assert r.status_code == 503
        r = c.post("/v1/voice/stt", files={"audio": ("a.wav", b"", "audio/wav")})
        assert r.status_code == 422
        r = c.post("/v1/voice/tts", json={"text": ""})
        assert r.status_code == 422
