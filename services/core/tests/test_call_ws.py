"""A participant's call over one WebSocket: ring, consent, question after question (no credits)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from core_testkit import body
from fake_gnani import FakeGnani
from fastapi import FastAPI
from fastapi.testclient import TestClient
from participant_bot import PHRASES
from test_media_ws import PCM, Env, drain, env, fake, make_env, token, until

from pramana_core.calls.runtime import CallTimers
from pramana_core.language.speakable import speakable
from pramana_core.voice import call as call_mod
from pramana_core.voice import media

pytestmark = pytest.mark.db
__all__ = ["env", "fake"]


@pytest.fixture(autouse=True)
def quick_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(call_mod, "IDLE_WAIT_S", 1.0)


def create(env: Env) -> dict[str, Any]:
    r = env.client.post("/v1/investigations", json=body(fault="CB_C2_7.tripped"))
    assert r.status_code == 201, r.text
    return dict(r.json())


def truthful(env: Env, inv_id: str, q: dict[str, Any]) -> str:
    """What the addressee would say, from their own simulator view."""
    a = q["action"]
    tok = env.client.post(f"/v1/investigations/{inv_id}/participants/{a['participant_id']}/token")
    h = {"Authorization": f"Bearer {tok.json()['token']}"}
    sid = tok.json()["scenario_id"]
    if a["requires_move"]:
        env.sim.post(f"/sim/v1/scenarios/{sid}/move", json={"to": a["location_id"]}, headers=h)
    if q.get("kind") == "challenge":
        view = env.sim.get(f"/sim/v1/scenarios/{sid}/view", headers=h).json()
        token_view = next(
            item for item in view["presence_tokens"] if item["token_id"] == q["presence_token_id"]
        )
        rendered = token_view["display_texts"][q["language"]]
        value = rendered.rsplit(" ", maxsplit=1)[-1].rstrip(".।")
        return " ".join(value)
    seen = env.sim.post(
        f"/sim/v1/scenarios/{sid}/observe", json={"probe_id": a["probe_id"]}, headers=h
    )
    return PHRASES[seen.json()["value"]]


def url(inv_id: str, pid: str) -> str:
    return f"/v1/investigations/{inv_id}/participants/{pid}/call"


def answer_and_get(env: Env, ws: Any, inv_id: str) -> dict[str, Any]:
    """Answer the question this call is asking, by voice; return the answer frame."""
    ready = until(ws, "ready")[-1]
    state = env.client.get(f"/v1/investigations/{inv_id}").json()
    env.fake.transcript = truthful(env, inv_id, state["pending_question"])
    assert ready["question_id"] == state["pending_question"]["id"]
    ws.send_bytes(PCM)
    ws.send_text(json.dumps({"type": "commit"}))
    return until(ws, "answer")[-1]


def events(env: Env, inv_id: str) -> list[dict[str, Any]]:
    return list(env.client.get(f"/v1/investigations/{inv_id}/events").json())


def test_a_call_rings_asks_consent_and_asks_question_after_question(env: Env) -> None:
    inv = create(env)
    pid = inv["pending_question"]["action"]["participant_id"]
    with env.client.websocket_connect(url(inv["id"], pid)) as ws:
        ws.send_text(
            json.dumps({"type": "start", "token": token(env, inv["id"], pid), "play": True})
        )
        ringing = until(ws, "ringing")[-1]
        assert ringing["participant_id"] == pid
        ws.send_text(json.dumps({"type": "accept"}))
        consent = until(ws, "consent_request")[-1]
        assert "?" in consent["text"]
        until(ws, "tts_end")
        assert env.tts.tts_requests[0]["text"] == speakable(consent["text"], ringing["language"])
        ws.send_text(json.dumps({"type": "consent", "answer": "yes"}))
        answered = [answer_and_get(env, ws, inv["id"])]
        # Keep answering while the engine addresses this same person.
        while True:
            state = env.client.get(f"/v1/investigations/{inv['id']}").json()
            q = state["pending_question"]
            if q is None or q["action"]["participant_id"] != pid:
                break
            answered.append(answer_and_get(env, ws, inv["id"]))
        msgs, _, code = drain(ws, calls=True)
    assert code == 1000
    assert msgs[-1] == {"type": "call_end", "reason": "nothing more to ask"}
    states = [m["state"] for m in msgs if m["type"] == "call_state"]
    assert states[-2:] == ["CLOSING", "ENDED"]
    assert all(a["result"]["observation"]["modality"] == "voice" for a in answered)
    consented = [e for e in events(env, inv["id"]) if e["type"] == "ConsentRecorded"]
    assert consented[0]["payload"]["consented"] is True
    assert env.client.get(f"/v1/investigations/{inv['id']}/replay").json()["identical"]


def test_call_answers_presence_challenge_without_transcribing_the_code(env: Env) -> None:
    presets = env.client.get("/v1/investigations/presets")
    assert presets.status_code == 200, presets.text
    preset = next(item for item in presets.json() if item["id"] == "S7")
    created = env.client.post("/v1/investigations", json=preset["request"])
    assert created.status_code == 201, created.text
    inv = dict(created.json())

    for _ in range(12):
        q = inv["pending_question"]
        assert q is not None, "S7 ended before a call challenge could be tested"
        if q["kind"] == "challenge":
            break
        answer = env.client.post(
            f"/v1/investigations/{inv['id']}/answers",
            json={
                "question_id": q["id"],
                "participant_id": q["action"]["participant_id"],
                "text": truthful(env, inv["id"], q),
            },
        )
        assert answer.status_code == 200, answer.text
        inv = answer.json()["state"]
    else:
        raise AssertionError("S7 did not issue a presence challenge")

    q = inv["pending_question"]
    assert q is not None
    assert q["kind"] == "challenge"
    participant_id = q["action"]["participant_id"]
    with env.client.websocket_connect(url(inv["id"], participant_id)) as ws:
        ws.send_text(
            json.dumps(
                {
                    "type": "start",
                    "token": token(env, inv["id"], participant_id),
                    "play": True,
                }
            )
        )
        until(ws, "ringing")
        ws.send_text(json.dumps({"type": "accept"}))
        until(ws, "consent_request")
        ws.send_text(json.dumps({"type": "consent", "answer": "yes"}))
        until(ws, "ready")
        state = env.client.get(f"/v1/investigations/{inv['id']}").json()
        challenge = state["pending_question"]
        assert challenge is not None
        assert challenge["id"] == q["id"]
        env.fake.transcript = truthful(env, inv["id"], challenge)
        ws.send_bytes(PCM)
        ws.send_text(json.dumps({"type": "commit"}))
        answer_frame = until(ws, "answer")[-1]

    assert answer_frame["result"]["passed"] is True
    assert "observation" not in answer_frame["result"]
    assert "transcript" not in answer_frame
    events_after = events(env, inv["id"])
    assert any(
        event["type"] == "ChallengeResult" and event["payload"]["result"] == "passed"
        for event in events_after
    )
    assert env.client.get(f"/v1/investigations/{inv['id']}/replay").json()["identical"]


def test_declining_consent_takes_the_person_out_and_the_engine_asks_someone_else(
    env: Env,
) -> None:
    inv = create(env)
    q = inv["pending_question"]
    pid = q["action"]["participant_id"]
    with env.client.websocket_connect(url(inv["id"], pid)) as ws:
        ws.send_text(
            json.dumps({"type": "start", "token": token(env, inv["id"], pid), "play": False})
        )
        until(ws, "ringing")
        ws.send_text(json.dumps({"type": "accept"}))
        until(ws, "consent_request")
        ws.send_text(json.dumps({"type": "consent", "answer": "no"}))
        msgs, _, code = drain(ws, calls=True)
    assert code == 1000
    assert msgs[-1] == {"type": "call_end", "reason": "declined"}
    after = env.client.get(f"/v1/investigations/{inv['id']}").json()
    nxt = after["pending_question"]
    assert nxt is None or nxt["action"]["participant_id"] != pid
    kinds = [e["type"] for e in events(env, inv["id"])]
    for kind in ("ConsentRecorded", "ParticipantUnavailable", "QuestionCancelled"):
        assert kind in kinds
    assert env.client.get(f"/v1/investigations/{inv['id']}/replay").json()["identical"]
    # The withdrawn question can no longer be answered.
    r = env.client.post(
        f"/v1/investigations/{inv['id']}/answers",
        json={"question_id": q["id"], "participant_id": pid, "text": "haan"},
    )
    assert r.status_code == 409


def test_an_unanswered_ring_releases_the_person(
    migrated_db: str, sim_app: FastAPI, fake: FakeGnani, monkeypatch: pytest.MonkeyPatch
) -> None:
    timers = CallTimers(ring_s=0.5, reprompt_s=0.4, unavailable_s=1.2)
    monkeypatch.setattr(call_mod, "CALL_TIMERS", timers)
    app, tts = make_env(migrated_db, sim_app, fake)
    with TestClient(app) as client:
        env = Env(client, TestClient(sim_app), fake, tts)
        inv = create(env)
        pid = inv["pending_question"]["action"]["participant_id"]
        with env.client.websocket_connect(url(inv["id"], pid)) as ws:
            ws.send_text(
                json.dumps({"type": "start", "token": token(env, inv["id"], pid), "play": False})
            )
            msgs, _, code = drain(ws, calls=True)
        after = env.client.get(f"/v1/investigations/{inv['id']}").json()
    assert msgs[-1] == {"type": "call_end", "reason": "not answered"}
    assert code == 1000
    assert [m["state"] for m in msgs if m["type"] == "call_state"] == ["UNAVAILABLE", "ENDED"]
    nxt = after["pending_question"]
    assert nxt is None or nxt["action"]["participant_id"] != pid


def test_silence_during_a_call_releases_the_person(
    migrated_db: str, sim_app: FastAPI, fake: FakeGnani, monkeypatch: pytest.MonkeyPatch
) -> None:
    timers = CallTimers(reprompt_s=0.4, unavailable_s=1.2)
    monkeypatch.setattr(call_mod, "CALL_TIMERS", timers)
    monkeypatch.setattr(media, "TIMER_POLL_S", 0.05)
    app, tts = make_env(migrated_db, sim_app, fake)
    with TestClient(app) as client:
        env = Env(client, TestClient(sim_app), fake, tts)
        inv = create(env)
        q = inv["pending_question"]
        pid = q["action"]["participant_id"]
        with env.client.websocket_connect(url(inv["id"], pid)) as ws:
            ws.send_text(
                json.dumps({"type": "start", "token": token(env, inv["id"], pid), "play": False})
            )
            until(ws, "ringing")
            ws.send_text(json.dumps({"type": "accept"}))
            until(ws, "consent_request")
            ws.send_text(json.dumps({"type": "consent", "answer": "yes"}))
            msgs, _, code = drain(ws, calls=True)
        after = env.client.get(f"/v1/investigations/{inv['id']}").json()
        replay = env.client.get(f"/v1/investigations/{inv['id']}/replay").json()
    assert code == 4408
    assert [m["type"] for m in msgs].count("reprompt") == 1
    assert msgs[-1] == {"type": "call_end", "reason": "silent"}
    nxt = after["pending_question"]
    assert nxt is None or nxt["id"] != q["id"]
    assert replay["identical"]


@pytest.mark.parametrize(("who", "code"), [("forged", 4401), ("other", 4403)])
def test_call_tokens_are_checked(env: Env, who: str, code: int) -> None:
    inv = create(env)
    pid = inv["pending_question"]["action"]["participant_id"]
    other = next(p["id"] for p in inv["participants"] if p["id"] != pid)
    tok = "abc.def" if who == "forged" else token(env, inv["id"], other)
    with env.client.websocket_connect(url(inv["id"], pid)) as ws:
        ws.send_text(json.dumps({"type": "start", "token": tok}))
        _msgs, _, closed = drain(ws, calls=True)
    assert closed == code
    assert not env.fake.seen_headers  # nothing reached Gnani


def test_a_waiting_call_sends_heartbeats(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proxies close silent sockets (Cloudflare after about 100 s): an idle call keeps talking.
    monkeypatch.setattr(call_mod, "HEARTBEAT_S", 0.2)
    monkeypatch.setattr(call_mod, "IDLE_WAIT_S", 1.0)
    inv = create(env)
    asked = inv["pending_question"]["action"]["participant_id"]
    pid = next(p["id"] for p in inv["participants"] if p["id"] != asked)  # nothing to ask them
    with env.client.websocket_connect(url(inv["id"], pid)) as ws:
        ws.send_text(
            json.dumps({"type": "start", "token": token(env, inv["id"], pid), "play": False})
        )
        until(ws, "ringing")
        ws.send_text(json.dumps({"type": "accept"}))
        until(ws, "consent_request")
        ws.send_text(json.dumps({"type": "consent", "answer": "yes"}))
        msgs, _, code = drain(ws, calls=True)
    assert len([m for m in msgs if m["type"] == "idle"]) >= 3
    assert msgs[-1] == {"type": "call_end", "reason": "nothing more to ask"}
    assert code == 1000
    assert not env.fake.seen_headers  # waiting costs nothing


def test_two_people_on_calls_at_once_in_one_investigation(env: Env) -> None:
    """Parallel calls (docs/adr/0011): two participants are asked at the same time, each over
    their own call socket and recognizer session, and both answers go through the one writer."""
    r = env.client.post(
        "/v1/investigations", json={**body(fault="CB_C2_7.tripped"), "max_parallel_calls": 3}
    )
    assert r.status_code == 201, r.text
    inv = r.json()
    first, second = inv["pending_questions"][:2]
    pa, pb = first["action"]["participant_id"], second["action"]["participant_id"]
    assert pa != pb
    with (
        env.client.websocket_connect(url(inv["id"], pa)) as wa,
        env.client.websocket_connect(url(inv["id"], pb)) as wb,
    ):
        for ws, pid in ((wa, pa), (wb, pb)):
            ws.send_text(
                json.dumps({"type": "start", "token": token(env, inv["id"], pid), "play": False})
            )
            until(ws, "ringing")
            ws.send_text(json.dumps({"type": "accept"}))
            until(ws, "consent_request")
            ws.send_text(json.dumps({"type": "consent", "answer": "yes"}))
        ready_a = until(wa, "ready")[-1]
        ready_b = until(wb, "ready")[-1]
        assert {ready_a["question_id"], ready_b["question_id"]} == {first["id"], second["id"]}
        # Both recognizer sessions are open at once; the first answer arrives on call A.
        env.fake.transcript = truthful(env, inv["id"], first)
        wa.send_bytes(PCM)
        wa.send_text(json.dumps({"type": "commit"}))
        got_a = until(wa, "answer")[-1]
        assert got_a["result"]["observation"]["participant_id"] == pa
        # Call B's question is still wanted (or was withdrawn because A settled it).
        state = env.client.get(f"/v1/investigations/{inv['id']}").json()
        still = second["id"] in {q["id"] for q in state["pending_questions"]}
        if still:
            env.fake.transcript = truthful(env, inv["id"], second)
            wb.send_bytes(PCM)
            wb.send_text(json.dumps({"type": "commit"}))
            got_b = until(wb, "answer")[-1]
            assert got_b["result"]["observation"]["participant_id"] == pb
        else:
            until(wb, "question_withdrawn")
        for ws in (wa, wb):
            ws.send_text(json.dumps({"type": "stop"}))
    log = events(env, inv["id"])
    voiced = [
        e["payload"]["evidence"]["participant_id"]
        for e in log
        if e["type"] == "ObservationRecorded" and e["payload"]["evidence"]["modality"] == "voice"
    ]
    assert voiced[:2] == ([pa, pb] if still else [pa])
    assert env.client.get(f"/v1/investigations/{inv['id']}/replay").json()["identical"]


def test_a_question_withdrawn_while_its_answer_is_submitted_ends_the_turn_not_the_call(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live parallel run, 2026-11-05: another person's answer withdrew this question while this
    person's spoken answer was being submitted. That is a withdrawal, not a fatal error."""
    from pramana_core.db import QuestionRow
    from pramana_core.errors import ApiError

    r = env.client.post(
        "/v1/investigations", json={**body(fault="CB_C2_7.tripped"), "max_parallel_calls": 3}
    )
    inv = r.json()
    q = inv["pending_questions"][0]
    pid = q["action"]["participant_id"]
    svc = env.client.app.state.investigations  # type: ignore[attr-defined]

    async def withdrawn(*_: Any, **__: Any) -> Any:
        # Another answer withdrew it just now (as the scheduler does), then this one arrives.
        async with svc.db.transaction() as session:
            row = await session.get(QuestionRow, q["id"])
            row.status = "withdrawn"
        raise ApiError(409, "QUESTION_NOT_PENDING", "question was withdrawn")

    monkeypatch.setattr(svc, "answer", withdrawn)
    with env.client.websocket_connect(url(inv["id"], pid)) as ws:
        ws.send_text(
            json.dumps({"type": "start", "token": token(env, inv["id"], pid), "play": False})
        )
        until(ws, "ringing")
        ws.send_text(json.dumps({"type": "accept"}))
        until(ws, "consent_request")
        ws.send_text(json.dumps({"type": "consent", "answer": "yes"}))
        until(ws, "ready")
        env.fake.transcript = truthful(env, inv["id"], q)
        ws.send_bytes(PCM)
        ws.send_text(json.dumps({"type": "commit"}))
        msgs = until(ws, "question_withdrawn")
        assert not [m for m in msgs if m["type"] == "error" and m.get("fatal")]
        rest, _, code = drain(ws, calls=True)
    assert code == 1000
    assert rest[-1]["type"] == "call_end"
    assert rest[-1]["reason"] != "error"
