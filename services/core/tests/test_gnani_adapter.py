"""Gnani adapter tests against protocol emulations (no network, no credits).

REST calls use ``httpx.MockTransport``; realtime uses ``fake_gnani.FakeGnani``. Live calls are in
``tests/live/test_gnani_live.py`` and need GNANI_API_KEY.
"""

from __future__ import annotations

import asyncio
import io
import json
import struct
import time
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
from pramana_core.voice.gnani import GnaniClient, GnaniSttStream, VoiceError, wav_duration_s


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


async def test_stream_ignores_malformed_and_non_object_frames() -> None:
    class Socket:
        close_code = 1000
        close_reason = ""

        async def __aiter__(self) -> Any:
            for frame in ("{", "null", "[]", '{"type":"transcript","text":"yes"}'):
                yield frame

    stream = GnaniSttStream(Socket(), {}, False)  # type: ignore[arg-type]
    events = [event async for event in stream.events()]
    assert [event.type for event in events] == ["transcript", "closed"]


async def test_stream_never_sends_audio_beyond_reserved_limit() -> None:
    class Socket:
        def __init__(self) -> None:
            self.frames: list[bytes] = []

        async def send(self, frame: bytes) -> None:
            self.frames.append(frame)

    socket = Socket()
    stream = GnaniSttStream(socket, {}, False)  # type: ignore[arg-type]
    stream.max_audio_bytes = 1024
    with pytest.raises(VoiceError) as exc:
        await stream.send_pcm(bytes(2048))
    assert exc.value.code == "VOICE_STREAM_LIMIT"
    assert len(socket.frames) == 1


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
    # Live server (2026-11-04) rejects a comma list; candidates go as indic-auto + header.
    assert h["language_code"] == "indic-auto"
    assert h["lang_code"] == "indic-auto"
    assert h["x-language-candidates"] == "mr-IN,hi-IN"
    assert json.loads(h["x-keywords"]) == ["NAVA-WiFi", "बंद"]
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


async def test_closing_a_session_does_not_wait_for_gnanis_handshake() -> None:
    # Gnani takes about a second to complete a close; the next question must not wait for it.
    class SlowClose:
        closed = False

        async def close(self) -> None:
            await asyncio.sleep(1.0)
            SlowClose.closed = True

    stream = GnaniSttStream(SlowClose(), {"config": {}}, expect_v3=False)  # type: ignore[arg-type]
    started = time.perf_counter()
    await stream.aclose()
    assert time.perf_counter() - started < 0.1
    assert not SlowClose.closed
    await asyncio.sleep(1.2)
    assert SlowClose.closed  # it still completes, in the background


def sse(*events: tuple[str, dict[str, Any]]) -> bytes:
    return "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events).encode()


def b64(raw: bytes) -> str:
    import base64

    return base64.b64encode(raw).decode()


async def test_tts_stream_yields_headerless_pcm_in_order() -> None:
    """Timbre SSE with ``container: raw`` (format checked live on 2026-11-05)."""
    bodies: list[dict[str, Any]] = []
    pcm = bytes(range(256)) * 8  # 2,048 bytes

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/api/v1/tts/sse"
        bodies.append(json.loads(req.content))
        payload = sse(
            ("start", {"status": "streaming_started"}),
            ("chunk", {"chunk_index": 1, "audio": b64(pcm[:513]), "is_final": False}),  # odd
            ("chunk", {"chunk_index": 2, "audio": b64(pcm[513:]), "is_final": False}),
            ("complete", {"chunk_index": 3, "audio": "", "is_final": True}),
        )
        return httpx.Response(200, content=payload, headers={"content-type": "text/event-stream"})

    g = client(handler)
    got = [c async for c in g.synthesize_stream("WiFi dikh raha hai?", language="hi-en")]
    assert b"".join(got) == pcm
    assert all(len(c) % 2 == 0 for c in got)  # whole samples only
    assert bodies[0]["audio_config"]["container"] == "raw"
    assert (bodies[0]["model"], bodies[0]["voice"]) == ("timbre-v2.5", "Poorvi")
    await g.aclose()


@pytest.mark.parametrize(
    ("status", "ctype", "payload", "code"),
    [
        (402, "application/json", b'{"detail": "no credit"}', None),
        (200, "audio/wav", b"RIFF....", "VOICE_UNEXPECTED_AUDIO"),
        (
            200,
            "text/event-stream",
            sse(("error", {"type": "error", "message": "bad text"})),
            "VOICE_TTS_STREAM_ERROR",
        ),
        (
            200,
            "text/event-stream",
            sse(("start", {"status": "streaming_started"})),
            "VOICE_BAD_STREAM",
        ),
    ],
)
async def test_tts_stream_failures_are_typed(
    status: int, ctype: str, payload: bytes, code: str | None
) -> None:
    g = client(lambda _: httpx.Response(status, content=payload, headers={"content-type": ctype}))
    with pytest.raises(VoiceError) as err:
        _ = [c async for c in g.synthesize_stream("hello", language="en-IN")]
    if code is not None:
        assert err.value.code == code
    await g.aclose()


@pytest.mark.parametrize(
    ("url", "provider"),
    [
        ("https://api.vachana.ai", "gnani"),
        ("https://api.vachana.ai/", "gnani"),
        ("http://api.vachana.ai", "other"),
        ("http://127.0.0.1:8190", "other"),
        ("https://api.vachana.ai.example.com", "other"),
        ("https://evil.example/api.vachana.ai", "other"),
    ],
)
def test_only_https_to_gnani_counts_as_the_live_provider(url: str, provider: str) -> None:
    from pramana_core.voice.gnani import provider_of

    assert provider_of(url) == provider


def test_voice_status_names_the_provider_the_core_actually_calls(migrated_db: str) -> None:
    live = create_app(core_settings(migrated_db, GNANI_API_KEY="k"))
    with TestClient(live) as c:
        status = c.get("/v1/voice/status").json()
        assert (status["provider"], status["provider_host"]) == ("gnani", "api.vachana.ai")
    emulated = create_app(
        core_settings(migrated_db, GNANI_API_KEY="k", GNANI_BASE_URL="http://127.0.0.1:8190")
    )
    with TestClient(emulated) as c:
        status = c.get("/v1/voice/status").json()
        assert (status["provider"], status["provider_host"]) == ("other", "127.0.0.1")
