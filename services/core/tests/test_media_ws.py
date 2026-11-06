"""Per-question media WebSocket against the local Prisma emulation (no credits)."""

from __future__ import annotations

import asyncio
import base64
import io
import json
import wave
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from core_testkit import body, core_settings, truncate_all
from fake_gnani import FakeGnani
from fastapi import FastAPI
from fastapi.testclient import TestClient
from participant_bot import PHRASES
from starlette.websockets import WebSocketDisconnect

from pramana_core.main import create_app

pytestmark = pytest.mark.db

PCM = b"\x01\x00" * 1600  # 0.1 s at 16 kHz


def wav(seconds: float = 0.5, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


STREAM_PCM = bytes([1, 0]) * 12_000  # 0.5 s of 24 kHz PCM16


class Tts:
    def __init__(self) -> None:
        self.status = 200
        self.calls = 0
        self.stt_text = ""
        """What the REST second decode hears ("" = nothing)."""
        self.stt_requests: list[httpx.Request] = []
        self.sse = False
        """Serve ``/api/v1/tts/sse`` as Timbre does (raw PCM chunks). Off: that path answers
        with a WAV body, which the core treats as "no stream" and falls back to REST."""
        self.sse_calls = 0

    def __call__(self, req: httpx.Request) -> httpx.Response:
        if req.url.path == "/stt/v3":
            # The REST second decode of a decision-critical answer: nothing heard by default,
            # so the person is asked again, as without a second decode.
            self.stt_requests.append(req)
            return httpx.Response(
                200, json={"success": True, "transcript": self.stt_text, "model": "prisma-v3.0"}
            )
        self.calls += 1
        if self.status != 200:
            return httpx.Response(self.status, json={"detail": "no"})
        if req.url.path == "/api/v1/tts/sse" and self.sse:
            self.sse_calls += 1
            pcm = STREAM_PCM
            step = len(pcm) // 4
            frames = [("start", {"status": "streaming_started"})]
            for i in range(4):
                part = base64.b64encode(pcm[i * step : (i + 1) * step]).decode()
                frames.append(("chunk", {"chunk_index": i + 1, "audio": part, "is_final": False}))
            frames.append(("complete", {"chunk_index": 5, "audio": "", "is_final": True}))
            body = "".join(
                f"event: {e}" + chr(10) + f"data: {json.dumps(d)}" + chr(10) * 2 for e, d in frames
            )
            return httpx.Response(
                200, content=body.encode(), headers={"content-type": "text/event-stream"}
            )
        return httpx.Response(200, content=wav())


@dataclass
class Env:
    client: TestClient
    sim: TestClient
    fake: FakeGnani
    tts: Tts
    settings: dict[str, Any] = field(default_factory=dict)


@pytest.fixture
def fake() -> Iterator[FakeGnani]:
    server = FakeGnani().start()
    yield server
    server.stop()


def make_env(migrated_db: str, sim_app: FastAPI, fake: FakeGnani, **overrides: Any) -> Any:
    asyncio.run(truncate_all(migrated_db))
    tts = Tts()
    settings = {"GNANI_API_KEY": "k", "GNANI_BASE_URL": fake.base_url, **overrides}
    app = create_app(
        core_settings(migrated_db, **settings),
        sim_transport=httpx.ASGITransport(app=sim_app),
        gnani_transport=httpx.MockTransport(tts),
    )
    return app, tts


@pytest.fixture
def env(migrated_db: str, sim_app: FastAPI, fake: FakeGnani) -> Iterator[Env]:
    app, tts = make_env(migrated_db, sim_app, fake)
    with TestClient(app) as client:
        yield Env(client, TestClient(sim_app), fake, tts)


def start(env: Env) -> tuple[dict[str, Any], dict[str, Any], str]:
    """Create S1; return (state, pending question, truthful spoken answer)."""
    state = env.client.post("/v1/investigations", json=body(fault="CB_C2_7.tripped")).json()
    q = state["pending_question"]
    a = q["action"]
    tok = env.client.post(
        f"/v1/investigations/{state['id']}/participants/{a['participant_id']}/token"
    ).json()
    h = {"Authorization": f"Bearer {tok['token']}"}
    if a["requires_move"]:
        env.sim.post(
            f"/sim/v1/scenarios/{tok['scenario_id']}/move", json={"to": a["location_id"]}, headers=h
        )
    seen = env.sim.post(
        f"/sim/v1/scenarios/{tok['scenario_id']}/observe",
        json={"probe_id": a["probe_id"]},
        headers=h,
    ).json()
    return state, q, PHRASES[seen["value"]]


def token(env: Env, inv_id: str, pid: str) -> str:
    out: str = env.client.post(f"/v1/investigations/{inv_id}/participants/{pid}/token").json()[
        "token"
    ]
    return out


def url(state: dict[str, Any], q: dict[str, Any]) -> str:
    return f"/v1/investigations/{state['id']}/questions/{q['id']}/media"


CALL_FRAMES = {"call_state", "stop_playback", "reprompt"}
"""Call-runtime frames, checked by their own tests; the protocol tests skip them."""


def drain(ws: Any, *, calls: bool = False) -> tuple[list[dict[str, Any]], int, int | None]:
    """Read until the server closes: (json messages, binary bytes, close code)."""
    msgs: list[dict[str, Any]] = []
    binary = 0
    while True:
        try:
            m = ws.receive()
        except WebSocketDisconnect as exc:
            return msgs, binary, exc.code
        if m["type"] == "websocket.close":
            return msgs, binary, m.get("code")
        if m.get("bytes") is not None:
            binary += len(m["bytes"])
        elif m.get("text") is not None:
            msg = json.loads(m["text"])
            if calls or msg["type"] not in CALL_FRAMES:
                msgs.append(msg)


def until(ws: Any, kind: str) -> list[dict[str, Any]]:
    out = []
    while True:
        m = ws.receive()
        if m.get("text") is None:
            continue
        msg = json.loads(m["text"])
        if msg["type"] in CALL_FRAMES and kind not in CALL_FRAMES:
            continue
        out.append(msg)
        if msg["type"] == kind:
            return out


def text_frame(ws: Any) -> dict[str, Any]:
    """The next protocol (non call-runtime) JSON frame."""
    while True:
        msg: dict[str, Any] = json.loads(ws.receive_text())
        if msg["type"] not in CALL_FRAMES:
            return msg


def test_spoken_answer_end_to_end(env: Env) -> None:
    state, q, phrase = start(env)
    env.fake.transcript = phrase
    pid = q["action"]["participant_id"]
    with env.client.websocket_connect(url(state, q)) as ws:
        ws.send_text(json.dumps({"type": "start", "token": token(env, state["id"], pid)}))
        ready = text_frame(ws)
        assert ready["type"] == "ready"
        assert ready["question_id"] == q["id"]
        assert ready["text"] == q["text"]
        assert ready["model_confirmed"] is True
        tts_start = text_frame(ws)
        assert tts_start["type"] == "tts_start"
        got = 0
        while got < tts_start["bytes"]:
            got += len(ws.receive_bytes())
        assert text_frame(ws) == {"type": "tts_end", "utt_id": 1}
        ws.send_bytes(PCM)
        ws.send_bytes(PCM)
        ws.send_text(json.dumps({"type": "commit"}))
        msgs, _, code = drain(ws)
    kinds = [m["type"] for m in msgs]
    assert kinds == ["speech_start", "processing", "transcript", "answer"]
    assert msgs[2]["text"] == phrase
    result = msgs[3]["result"]
    assert result["observation"]["modality"] == "voice"
    assert result["observation"]["question_id"] == q["id"]
    assert code == 1000
    # Question-conditioned Prisma session.
    h = env.fake.seen_headers[-1]
    assert h["model"] == "prisma-v3.0"
    assert h["x-min-segment-ms"] == "100"
    assert h["x-language-candidates"] == "hi-IN,en-IN"
    assert h["format"] == "codemix"
    assert json.loads(h["keyterms"])
    assert env.fake.frame_sizes
    assert set(env.fake.frame_sizes) == {1024}
    after = env.client.get(f"/v1/investigations/{state['id']}").json()
    assert after["pending_question"]["id"] != q["id"]
    assert env.client.get(f"/v1/investigations/{state['id']}/replay").json()["identical"]


def test_empty_transcript_records_nothing_and_keeps_listening(env: Env) -> None:
    state, q, phrase = start(env)
    env.fake.transcripts = ["", phrase]
    pid = q["action"]["participant_id"]
    before = len(env.client.get(f"/v1/investigations/{state['id']}").json()["observations"])
    with env.client.websocket_connect(url(state, q)) as ws:
        ws.send_text(
            json.dumps(
                {"type": "start", "token": token(env, state["id"], pid), "play_question": False}
            )
        )
        until(ws, "ready")
        ws.send_bytes(PCM)
        ws.send_text(json.dumps({"type": "commit"}))
        until(ws, "empty_transcript")
        mid = env.client.get(f"/v1/investigations/{state['id']}").json()
        assert len(mid["observations"]) == before
        assert mid["pending_question"]["id"] == q["id"]
        ws.send_bytes(PCM)
        ws.send_text(json.dumps({"type": "commit"}))
        msgs, _, code = drain(ws)
    assert [m["type"] for m in msgs][-2:] == ["transcript", "answer"]
    assert code == 1000
    assert env.tts.calls == 0  # play_question false: no paid TTS


def test_tap_answer_over_the_media_socket(env: Env) -> None:
    state, q, _ = start(env)
    pid = q["action"]["participant_id"]
    with env.client.websocket_connect(url(state, q)) as ws:
        ws.send_text(
            json.dumps(
                {"type": "start", "token": token(env, state["id"], pid), "play_question": False}
            )
        )
        until(ws, "ready")
        ws.send_text(json.dumps({"type": "tap_answer", "outcome": q["outcomes"][0]}))
        msgs, _, code = drain(ws)
    assert msgs[-1]["type"] == "answer"
    assert msgs[-1]["result"]["extraction"]["method"] == "structured"
    assert code == 1000


@pytest.mark.parametrize(
    ("who", "expect"),
    [("forged", 4401), ("other", 4403)],
)
def test_tokens_are_checked(env: Env, who: str, expect: int) -> None:
    state, q, _ = start(env)
    pid = q["action"]["participant_id"]
    other = next(p["id"] for p in state["participants"] if p["id"] != pid)
    tok = "abc.def" if who == "forged" else token(env, state["id"], other)
    with env.client.websocket_connect(url(state, q)) as ws:
        ws.send_text(json.dumps({"type": "start", "token": tok}))
        _msgs, _, code = drain(ws)
    assert code == expect
    assert not env.fake.seen_headers  # nothing reached Gnani


def test_first_message_must_be_start(env: Env) -> None:
    state, q, _ = start(env)
    with env.client.websocket_connect(url(state, q)) as ws:
        ws.send_text(json.dumps({"type": "commit"}))
        msgs, _, code = drain(ws)
    assert code == 4400
    assert msgs[0]["code"] == "MEDIA_EXPECTED_START"


def test_unknown_and_answered_questions_are_refused(env: Env) -> None:
    state, q, phrase = start(env)
    pid = q["action"]["participant_id"]
    tok = token(env, state["id"], pid)
    bad = f"/v1/investigations/{state['id']}/questions/q_nope/media"
    with env.client.websocket_connect(bad) as ws:
        ws.send_text(json.dumps({"type": "start", "token": tok}))
        _, _, code = drain(ws)
    assert code == 4404
    env.client.post(
        f"/v1/investigations/{state['id']}/answers",
        json={"question_id": q["id"], "participant_id": pid, "text": phrase},
    )
    with env.client.websocket_connect(url(state, q)) as ws:
        ws.send_text(json.dumps({"type": "start", "token": tok}))
        msgs, _, code = drain(ws)
    assert code == 4409
    assert msgs[0]["code"] == "QUESTION_NOT_PENDING"


def test_question_answered_elsewhere_mid_stream(env: Env) -> None:
    state, q, phrase = start(env)
    pid = q["action"]["participant_id"]
    with env.client.websocket_connect(url(state, q)) as ws:
        ws.send_text(
            json.dumps(
                {"type": "start", "token": token(env, state["id"], pid), "play_question": False}
            )
        )
        until(ws, "ready")
        ws.send_bytes(PCM)
        r = env.client.post(
            f"/v1/investigations/{state['id']}/answers",
            json={"question_id": q["id"], "participant_id": pid, "text": phrase},
        )
        assert r.status_code == 200
        msgs, _, code = drain(ws)
    assert code == 4409
    assert msgs[-1]["code"] == "QUESTION_NOT_PENDING"
    obs = env.client.get(f"/v1/investigations/{state['id']}").json()["observations"]
    assert [o["modality"] for o in obs if o["question_id"] == q["id"]] == ["text"]


def test_one_session_per_token(env: Env) -> None:
    state, q, _ = start(env)
    tok = token(env, state["id"], q["action"]["participant_id"])
    start_msg = json.dumps({"type": "start", "token": tok, "play_question": False})
    with env.client.websocket_connect(url(state, q)) as first:
        first.send_text(start_msg)
        until(first, "ready")
        with env.client.websocket_connect(url(state, q)) as second:
            second.send_text(start_msg)
            msgs, _, code = drain(second)
        assert code == 4409
        assert msgs[0]["code"] == "MEDIA_SESSION_ACTIVE"
        first.send_text(json.dumps({"type": "stop"}))
        _, _, code = drain(first)
    assert code == 1000


def test_bad_audio_frames_are_refused(env: Env) -> None:
    state, q, _ = start(env)
    tok = token(env, state["id"], q["action"]["participant_id"])
    with env.client.websocket_connect(url(state, q)) as ws:
        ws.send_text(json.dumps({"type": "start", "token": tok, "play_question": False}))
        until(ws, "ready")
        ws.send_bytes(b"\x01\x02\x03")  # not whole PCM16 samples
        msgs, _, code = drain(ws)
    assert code == 4400
    assert msgs[-1]["code"] == "MEDIA_BAD_FRAME"


def test_tts_failure_is_not_fatal(env: Env) -> None:
    state, q, phrase = start(env)
    env.fake.transcript = phrase
    env.tts.status = 402  # out of credit for TTS
    tok = token(env, state["id"], q["action"]["participant_id"])
    with env.client.websocket_connect(url(state, q)) as ws:
        ws.send_text(json.dumps({"type": "start", "token": tok}))
        msgs = until(ws, "error")
        assert msgs[-1]["fatal"] is False
        ws.send_bytes(PCM)
        ws.send_text(json.dumps({"type": "commit"}))
        msgs, _, code = drain(ws)
    assert msgs[-1]["type"] == "answer"
    assert code == 1000


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"VOICE_DAILY_BUDGET_INR": 0.001}, "VOICE_BUDGET_EXCEEDED"),
        ({"GNANI_API_KEY": ""}, "VOICE_NOT_CONFIGURED"),
    ],
)
def test_voice_limits_close_with_typed_errors(
    migrated_db: str, sim_app: FastAPI, fake: FakeGnani, overrides: dict[str, Any], error: str
) -> None:
    app, tts = make_env(migrated_db, sim_app, fake, **overrides)
    with TestClient(app) as client:
        env = Env(client, TestClient(sim_app), fake, tts)
        state, q, _ = start(env)
        tok = token(env, state["id"], q["action"]["participant_id"])
        with client.websocket_connect(url(state, q)) as ws:
            ws.send_text(json.dumps({"type": "start", "token": tok}))
            msgs, _, code = drain(ws)
    assert msgs[-1]["code"] == error
    assert code == (4503 if error == "VOICE_NOT_CONFIGURED" else 4429)
    assert not fake.seen_headers


def test_concurrent_stream_cap(migrated_db: str, sim_app: FastAPI, fake: FakeGnani) -> None:
    app, tts = make_env(migrated_db, sim_app, fake, GNANI_MAX_STREAMS=1)
    with TestClient(app) as client:
        env = Env(client, TestClient(sim_app), fake, tts)
        state, q, _ = start(env)
        pid = q["action"]["participant_id"]
        with client.websocket_connect(url(state, q)) as first:
            first.send_text(
                json.dumps(
                    {
                        "type": "start",
                        "token": token(env, state["id"], pid),
                        "play_question": False,
                    }
                )
            )
            until(first, "ready")
            with client.websocket_connect(url(state, q)) as second:
                second.send_text(
                    json.dumps({"type": "start", "token": token(env, state["id"], pid)})
                )
                msgs, _, code = drain(second)
            assert code == 4429
            assert msgs[-1]["code"] == "VOICE_TOO_MANY_STREAMS"
            first.send_text(json.dumps({"type": "stop"}))
            drain(first)


# -- the call runtime drives the session ---------------------------------------------------


def states(msgs: list[dict[str, Any]]) -> list[str]:
    return [m["state"] for m in msgs if m["type"] == "call_state"]


def test_call_runtime_runs_a_spoken_turn(env: Env) -> None:
    state, q, phrase = start(env)
    env.fake.transcript = phrase
    tok = token(env, state["id"], q["action"]["participant_id"])
    with env.client.websocket_connect(url(state, q)) as ws:
        ws.send_text(json.dumps({"type": "start", "token": tok}))
        until(ws, "tts_end")
        ws.send_text(json.dumps({"type": "playback_done"}))
        until(ws, "call_state")  # LISTENING
        ws.send_bytes(PCM)
        ws.send_text(json.dumps({"type": "commit"}))
        msgs, _, code = drain(ws, calls=True)
    assert code == 1000
    assert states(msgs) == ["EXTRACTING", "IDLE", "CLOSING", "ENDED"]
    assert not [m for m in msgs if m["type"] == "stop_playback"]  # no barge-in


def test_speaking_over_the_question_stops_playback(env: Env) -> None:
    state, q, phrase = start(env)
    env.fake.transcript = phrase
    tok = token(env, state["id"], q["action"]["participant_id"])
    with env.client.websocket_connect(url(state, q)) as ws:
        ws.send_text(json.dumps({"type": "start", "token": tok}))
        until(ws, "ready")
        ws.send_bytes(PCM)  # speak while the prompt is still being generated
        stop = until(ws, "stop_playback")
        ws.send_text(json.dumps({"type": "commit"}))
        msgs, _, code = drain(ws, calls=True)
    assert not [m for m in stop if m["type"] == "tts_end"]
    utt = stop[-1]["utt_id"]
    assert stop[-1] == {"type": "stop_playback", "utt_id": utt}
    assert {"type": "call_state", "state": "LISTENING", "event": "barge_in", "utt_id": utt} in stop
    assert msgs[-1]["state"] == "ENDED"
    assert code == 1000


def test_silence_reprompts_once_then_gives_up(
    migrated_db: str, sim_app: FastAPI, fake: FakeGnani, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pramana_core.calls.runtime import CallTimers
    from pramana_core.voice import media

    monkeypatch.setattr(media, "CALL_TIMERS", CallTimers(reprompt_s=0.4, unavailable_s=1.2))
    monkeypatch.setattr(media, "TIMER_POLL_S", 0.05)
    app, tts = make_env(migrated_db, sim_app, fake)
    with TestClient(app) as client:
        env = Env(client, TestClient(sim_app), fake, tts)
        state, q, _ = start(env)
        tok = token(env, state["id"], q["action"]["participant_id"])
        with env.client.websocket_connect(url(state, q)) as ws:
            ws.send_text(json.dumps({"type": "start", "token": tok, "play_question": False}))
            msgs, _, code = drain(ws, calls=True)
        after = env.client.get(f"/v1/investigations/{state['id']}").json()
    kinds = [m["type"] for m in msgs]
    assert kinds.count("reprompt") == 1
    assert next(m for m in msgs if m["type"] == "reprompt")["text"] == q["text"]
    assert states(msgs)[-2:] == ["UNAVAILABLE", "ENDED"]
    assert msgs[-1]["type"] == "error"
    assert msgs[-1]["code"] == "PARTICIPANT_SILENT"
    assert code == 4408
    assert after["pending_question"]["id"] == q["id"]  # nothing recorded; ask again later
    assert tts.calls == 0


def test_hanging_up_ends_the_call(env: Env) -> None:
    state, q, _ = start(env)
    tok = token(env, state["id"], q["action"]["participant_id"])
    with env.client.websocket_connect(url(state, q)) as ws:
        ws.send_text(json.dumps({"type": "start", "token": tok, "play_question": False}))
        until(ws, "ready")
        ws.send_text(json.dumps({"type": "stop"}))
        msgs, _, code = drain(ws, calls=True)
    assert states(msgs)[-2:] == ["CLOSING", "ENDED"]
    assert code == 1000


def test_live_answer_confirmed_by_a_second_decode_is_not_asked_again(env: Env) -> None:
    state, q, phrase = start(env)
    env.fake.transcript = phrase
    env.tts.stt_text = phrase  # the independent decode of the same audio agrees
    pid = q["action"]["participant_id"]
    with env.client.websocket_connect(url(state, q)) as ws:
        ws.send_text(
            json.dumps(
                {"type": "start", "token": token(env, state["id"], pid), "play_question": False}
            )
        )
        until(ws, "ready")
        ws.send_bytes(PCM)
        ws.send_bytes(PCM)
        ws.send_text(json.dumps({"type": "commit"}))
        msgs, _, code = drain(ws)
    assert code == 1000
    assert msgs[-1]["type"] == "answer"
    events = env.client.get(f"/v1/investigations/{state['id']}/events").json()
    confirmed = [e["payload"] for e in events if e["type"] == "ObservationConfirmed"]
    assert env.tts.stt_requests  # the first S1 answer is decision-critical: it was checked
    assert confirmed[-1]["method"] == "second_decode"
    assert b"keyterms" not in env.tts.stt_requests[-1].content
    after = env.client.get(f"/v1/investigations/{state['id']}").json()
    assert (after["pending_question"] or {}).get("kind") != "confirm"
    assert env.client.get(f"/v1/investigations/{state['id']}/replay").json()["identical"]


def _question_audio(ws: Any) -> tuple[dict[str, Any], bytes]:
    """Read one question's audio: its ``tts_start`` frame and the bytes up to ``tts_end``."""
    start_msg = text_frame(ws)
    assert start_msg["type"] == "tts_start"
    audio = b""
    while True:
        msg = ws.receive()
        if msg.get("bytes") is not None:
            audio += msg["bytes"]
            continue
        frame = json.loads(msg["text"])
        if frame["type"] == "tts_end":
            assert frame["utt_id"] == start_msg["utt_id"]
            return start_msg, audio


def test_uncached_question_audio_is_streamed_then_cached(env: Env) -> None:
    """Timbre SSE: PCM pieces are forwarded as they arrive; the joined WAV is cached, so the
    same question next time is one WAV served from the cache at no cost."""
    env.tts.sse = True
    state, q, _ = start(env)
    pid = q["action"]["participant_id"]
    with env.client.websocket_connect(url(state, q)) as ws:
        ws.send_text(json.dumps({"type": "start", "token": token(env, state["id"], pid)}))
        assert text_frame(ws)["type"] == "ready"
        first, audio = _question_audio(ws)
        ws.send_text(json.dumps({"type": "stop"}))
    assert first["format"] == "pcm_s16le"
    assert (first["sample_rate"], first["channels"], first["streaming"]) == (24000, 1, True)
    assert audio == STREAM_PCM  # every sample, in order, no header
    assert env.tts.sse_calls == 1
    cache = env.client.app.state.question_audio  # type: ignore[attr-defined]
    assert len(cache) == 1
    with env.client.websocket_connect(url(state, q)) as ws:
        ws.send_text(json.dumps({"type": "start", "token": token(env, state["id"], pid)}))
        assert text_frame(ws)["type"] == "ready"
        again, wav_bytes = _question_audio(ws)
        ws.send_text(json.dumps({"type": "stop"}))
    assert (again["format"], again["cached"]) == ("wav", True)
    assert wav_bytes[:4] == b"RIFF"
    assert wav_bytes.endswith(STREAM_PCM)
    assert env.tts.sse_calls == 1  # nothing paid the second time


def test_a_failed_stream_falls_back_to_one_wav(env: Env) -> None:
    """No stream (here the TTS host answers the SSE path with a WAV body): one REST WAV."""
    env.tts.sse = False
    state, q, _ = start(env)
    pid = q["action"]["participant_id"]
    with env.client.websocket_connect(url(state, q)) as ws:
        ws.send_text(json.dumps({"type": "start", "token": token(env, state["id"], pid)}))
        assert text_frame(ws)["type"] == "ready"
        first, audio = _question_audio(ws)
        ws.send_text(json.dumps({"type": "stop"}))
    assert first["format"] == "wav"
    assert audio[:4] == b"RIFF"


def test_listen_streams_an_uncached_question_then_serves_it_from_the_cache(env: Env) -> None:
    """GET .../audio on a miss: a WAV header with an open-ended length, then Timbre's PCM as
    it arrives (the browser plays it while downloading). The next request is the cached WAV."""
    env.tts.sse = True
    state, q, _ = start(env)
    url_audio = f"/v1/investigations/{state['id']}/questions/{q['id']}/audio"
    first = env.client.get(url_audio)
    assert first.status_code == 200
    assert first.headers["x-audio-streamed"] == "true"
    assert first.headers["content-type"].startswith("audio/wav")
    head, pcm = first.content[:44], first.content[44:]
    assert head[:4] == b"RIFF"
    assert head[8:16] == b"WAVEfmt "
    assert head[36:40] == b"data"
    assert int.from_bytes(head[24:28], "little") == 24000
    assert pcm == STREAM_PCM
    again = env.client.get(url_audio)
    assert again.headers["x-audio-cached"] == "true"
    assert "x-audio-streamed" not in again.headers
    with wave.open(io.BytesIO(again.content)) as w:  # the cached copy is a valid, sized WAV
        assert (w.getframerate(), w.getnframes()) == (24000, len(STREAM_PCM) // 2)
    assert env.tts.sse_calls == 1
