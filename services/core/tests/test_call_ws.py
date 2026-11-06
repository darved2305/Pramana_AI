"""A participant's call over one WebSocket: ring, consent, question after question (no credits)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from core_testkit import body
from fake_gnani import FakeGnani
from fastapi import FastAPI
from fastapi.testclient import TestClient
from participant_bot import PHRASES
from starlette.websockets import WebSocketDisconnect
from test_media_ws import PCM, Env, drain, env, fake, make_env, token, until

from pramana_core.calls.runtime import CallTimers
from pramana_core.voice import call as call_mod
from pramana_core.voice import media
from pramana_core.voice.call import ParticipantCall

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
            json.dumps({"type": "start", "token": token(env, inv["id"], pid), "play": False})
        )
        ringing = until(ws, "ringing")[-1]
        assert ringing["participant_id"] == pid
        ws.send_text(json.dumps({"type": "accept"}))
        consent = until(ws, "consent_request")[-1]
        assert "?" in consent["text"]
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


async def test_participant_disconnect_is_logged_with_socket_code_and_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entries: list[dict[str, Any]] = []

    class CaptureLog:
        def info(self, event: str, **fields: Any) -> None:
            entries.append({"event": event, **fields})

    class DisconnectedSocket:
        async def accept(self) -> None:
            pass

        async def receive_text(self) -> str:
            return json.dumps({"type": "start", "token": "token", "play": False})

        async def send_text(self, _text: str) -> None:
            raise AssertionError("a disconnected socket must not receive call_end")

        async def close(self, **_kwargs: Any) -> None:
            raise AssertionError("the server must not close a participant-disconnected socket")

    class CallService:
        def verify_participant_token(self, _token: str) -> Any:
            return SimpleNamespace(sub="p_riya", scn="scenario-1", jti="token-id")

        async def get(self, _inv_id: str) -> Any:
            participant = SimpleNamespace(
                id="p_riya", languages=SimpleNamespace(template_language="en")
            )
            return SimpleNamespace(participants=[participant])

        async def scenario_of(self, _inv_id: str) -> str:
            return "scenario-1"

    participant_call = ParticipantCall(
        DisconnectedSocket(),
        "inv-1",
        "p_riya",
        CallService(),  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        None,  # type: ignore[arg-type]
        media.ActiveSessions(),
        300,
    )

    async def disconnect(_language: str) -> str:
        raise WebSocketDisconnect(1000, "participant ended the call early")

    monkeypatch.setattr(call_mod, "log", CaptureLog())
    monkeypatch.setattr(participant_call, "_converse", disconnect)
    await participant_call.run()

    ended = next(entry for entry in entries if entry["event"] == "call_ended")
    assert ended["socket_close_code"] == 1000
    assert ended["socket_close_reason"] == "participant ended the call early"
    assert ended["call_end_sent"] is False


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


def test_hanging_up_while_waiting_is_handled_immediately(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(call_mod, "IDLE_WAIT_S", 2.0)
    monkeypatch.setattr(call_mod, "HEARTBEAT_S", 0.1)
    inv = create(env)
    asked = inv["pending_question"]["action"]["participant_id"]
    pid = next(p["id"] for p in inv["participants"] if p["id"] != asked)
    with env.client.websocket_connect(url(inv["id"], pid)) as ws:
        ws.send_text(
            json.dumps({"type": "start", "token": token(env, inv["id"], pid), "play": False})
        )
        until(ws, "ringing")
        ws.send_text(json.dumps({"type": "accept"}))
        until(ws, "consent_request")
        ws.send_text(json.dumps({"type": "consent", "answer": "yes"}))
        until(ws, "idle")
        ws.send_text(json.dumps({"type": "stop"}))
        messages, _, code = drain(ws, calls=True)

    assert code == 1000
    assert messages[-1] == {"type": "call_end", "reason": "later"}


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


@pytest.mark.parametrize("error_code", ["QUESTION_NOT_PENDING", "INVESTIGATION_NOT_ACTIVE"])
def test_a_question_withdrawn_while_its_answer_is_submitted_ends_the_turn_not_the_call(
    env: Env, monkeypatch: pytest.MonkeyPatch, error_code: str
) -> None:
    """Live parallel run, 2026-11-05: another person's answer withdrew this question while this
    person's spoken answer was being submitted. That is a withdrawal, not a fatal error."""
    from pramana_core.db import InvestigationRow, QuestionRow
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
            if error_code == "INVESTIGATION_NOT_ACTIVE":
                investigation = await session.get(InvestigationRow, inv["id"])
                investigation.status = "decided"
        raise ApiError(409, error_code, "question was withdrawn")

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


def test_call_survives_a_question_withdrawn_during_pending_lookup(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A concurrent answer can cancel a question between the state read and question fetch."""
    from pramana_contracts import SubmitAnswer
    from pramana_core.errors import ApiError
    from pramana_engine import Engine

    monkeypatch.setattr(call_mod, "IDLE_WAIT_S", 0.5)
    monkeypatch.setattr(call_mod, "HEARTBEAT_S", 0.1)
    response = env.client.post(
        "/v1/investigations",
        json={**body(fault="CB_C2_7.tripped"), "max_parallel_calls": 3},
    )
    assert response.status_code == 201, response.text
    inv = response.json()
    question, answering, *_ = inv["pending_questions"]
    pid = question["action"]["participant_id"]
    assert pid != answering["action"]["participant_id"]
    answering_text = truthful(env, inv["id"], answering)
    svc = env.client.app.state.investigations  # type: ignore[attr-defined]
    original = svc.pending_question
    raced = False
    moot_target = (pid, question["action"]["probe_id"])
    monkeypatch.setattr(
        Engine,
        "moot",
        lambda self, pending: [
            (action.participant_id, action.probe_id) == moot_target for action in pending
        ],
    )

    async def withdraw_during_lookup(
        investigation_id: str, question_id: str, participant_id: str | None = None
    ) -> Any:
        nonlocal raced
        if question_id == question["id"] and not raced:
            raced = True
            other_pid = answering["action"]["participant_id"]
            await svc.answer(
                investigation_id,
                SubmitAnswer(
                    question_id=answering["id"],
                    participant_id=other_pid,
                    text=answering_text,
                ),
            )
            raise ApiError(409, "QUESTION_NOT_PENDING", "question was withdrawn")
        return await original(investigation_id, question_id, participant_id)

    monkeypatch.setattr(svc, "pending_question", withdraw_during_lookup)
    with env.client.websocket_connect(url(inv["id"], pid)) as ws:
        ws.send_text(
            json.dumps({"type": "start", "token": token(env, inv["id"], pid), "play": False})
        )
        until(ws, "ringing")
        ws.send_text(json.dumps({"type": "accept"}))
        until(ws, "consent_request")
        ws.send_text(json.dumps({"type": "consent", "answer": "yes"}))
        messages, _, code = drain(ws, calls=True)

    assert raced
    assert code in {1000, 4408}, [(m["type"], m.get("event"), m.get("reason")) for m in messages]
    assert any(m["type"] == "question_withdrawn" for m in messages)
    assert messages[-1]["type"] == "call_end"
    assert messages[-1]["reason"] != "error"
    if code == 4408:
        assert messages[-1]["reason"] == "silent"
    fatal_errors = [m for m in messages if m["type"] == "error" and m.get("fatal")]
    if code == 4408:
        assert all(m["code"] == "PARTICIPANT_SILENT" for m in fatal_errors)
    else:
        assert not fatal_errors
