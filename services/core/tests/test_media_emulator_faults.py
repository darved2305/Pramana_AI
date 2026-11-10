"""Per-question recovery against the local wire-protocol emulator only."""

from __future__ import annotations

import asyncio
import json
import socket
import sys
import wave
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
from core_testkit import body, core_settings, truncate_all
from fastapi import FastAPI
from fastapi.testclient import TestClient
from participant_bot import PHRASES
from starlette.websockets import WebSocketDisconnect

from pramana_core.main import create_app

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from gnani_emulator import encode_clip, serve_in_thread, stop_in_thread

pytestmark = pytest.mark.db


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _next(ws: Any) -> dict[str, Any] | None:
    while True:
        try:
            frame = ws.receive()
        except WebSocketDisconnect:
            return None
        if frame.get("bytes") is not None:
            continue
        if frame.get("text"):
            return json.loads(frame["text"])


def _until(ws: Any, kind: str) -> dict[str, Any] | None:
    while (msg := _next(ws)) is not None:
        if msg.get("type") == kind:
            return msg
    return None


def _question(client: TestClient, sim: TestClient) -> tuple[dict[str, Any], dict[str, Any], str]:
    state = client.post("/v1/investigations", json=body(fault="CB_C2_7.tripped")).json()
    question = state["pending_question"]
    action = question["action"]
    issued = client.post(
        f"/v1/investigations/{state['id']}/participants/{action['participant_id']}/token"
    ).json()
    headers = {"Authorization": f"Bearer {issued['token']}"}
    if action["requires_move"]:
        sim.post(
            f"/sim/v1/scenarios/{issued['scenario_id']}/move",
            json={"to": action["location_id"]},
            headers=headers,
        )
    seen = sim.post(
        f"/sim/v1/scenarios/{issued['scenario_id']}/observe",
        json={"probe_id": action["probe_id"]},
        headers=headers,
    ).json()
    return state, question, PHRASES[seen["value"]]


def _answer_once(
    client: TestClient, state: dict[str, Any], question: dict[str, Any], phrase: str
) -> list[dict[str, Any]]:
    action = question["action"]
    issued = client.post(
        f"/v1/investigations/{state['id']}/participants/{action['participant_id']}/token"
    ).json()
    path = f"/v1/investigations/{state['id']}/questions/{question['id']}/media"
    clip = encode_clip(phrase)
    with wave.open(BytesIO(clip), "rb") as wav:
        pcm = wav.readframes(wav.getnframes())
    messages: list[dict[str, Any]] = []
    with client.websocket_connect(path) as ws:
        ws.send_text(json.dumps({"type": "start", "token": issued["token"]}))
        ready = _until(ws, "ready")
        assert ready is not None
        # Drain question synthesis before sending the participant's answer.
        if ready.get("protocol_emulator"):
            tts = _until(ws, "tts_start")
            if tts is not None:
                assert _until(ws, "tts_end") is not None
        for offset in range(0, len(pcm), 2048):
            ws.send_bytes(pcm[offset : offset + 2048])
        ws.send_text(json.dumps({"type": "capture_end", "capture_duration_ms": 600}))
        ws.send_text(json.dumps({"type": "commit"}))
        while (msg := _next(ws)) is not None:
            messages.append(msg)
            if msg.get("type") in {"answer", "error"}:
                break
    return messages


@pytest.mark.parametrize("fault", ["429", "5xx", "slow", "partial", "malformed", "noise", "drop"])
def test_emulator_fault_matrix_recovers_without_lost_or_duplicate_observations(
    migrated_db: str, sim_app: FastAPI, fault: str
) -> None:
    asyncio.run(truncate_all(migrated_db))
    stats, server = serve_in_thread(_port(), fault=fault, noise_seed=431)
    try:
        app = create_app(
            core_settings(
                migrated_db,
                GNANI_API_KEY="emulator-only",
                GNANI_BASE_URL=f"http://127.0.0.1:{server.config.port}",
                GNANI_PROTOCOL_EMULATOR=True,
            ),
            sim_transport=httpx.ASGITransport(app=sim_app),
        )
        with TestClient(app) as client, TestClient(sim_app) as sim:
            state, question, phrase = _question(client, sim)
            before = len(state["observations"])
            first = _answer_once(client, state, question, phrase)
            if fault == "drop":
                assert any(m.get("type") == "error" for m in first)
                after_drop = client.get(f"/v1/investigations/{state['id']}").json()
                assert len(after_drop["observations"]) == before
                assert after_drop["pending_question"]["id"] == question["id"]
                # The browser's retry affordance is covered in voice-recovery.spec.ts. A fresh
                # question socket after the one-shot upstream drop proves the answer is recoverable.
                second = _answer_once(client, state, question, phrase)
                assert sum(m.get("type") == "answer" for m in second) == 1
            else:
                assert sum(m.get("type") == "answer" for m in first) == 1
            final = client.get(f"/v1/investigations/{state['id']}").json()
            assert len(final["observations"]) == before + 1
            recorded = [o for o in final["observations"] if o["question_id"] == question["id"]]
            assert len(recorded) == 1
            assert final["pending_question"]["id"] != question["id"]
            assert client.get(f"/v1/investigations/{state['id']}/replay").json()["identical"]
            assert stats.fault_triggered == 1
            if fault == "noise":
                assert stats.noise_applied == 1
    finally:
        stop_in_thread(server)
