"""Voice inside a workspace: participant links speak and answer only in their own workspace."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from auth_testkit import CSRF, _seed, login
from core_testkit import body, core_settings, truncate_all
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_voice_turns import FakeGnaniHttp, wav

from pramana_core.main import create_app

pytestmark = pytest.mark.db


def keyed() -> dict[str, str]:
    return {**CSRF, "Idempotency-Key": uuid.uuid4().hex}


@pytest.fixture
def workspace_voice(
    migrated_db: str, sim_app: FastAPI
) -> Iterator[tuple[TestClient, FakeGnaniHttp, dict[str, Any], dict[str, Any]]]:
    asyncio.run(truncate_all(migrated_db))
    asyncio.run(_seed(migrated_db))
    fake = FakeGnaniHttp()
    app = create_app(
        core_settings(migrated_db, AUTH_REQUIRED=True, CORE_AUTOMATION_KEY="", GNANI_API_KEY="k"),
        sim_transport=httpx.ASGITransport(app=sim_app),
        gnani_transport=httpx.MockTransport(fake),
    )
    with TestClient(app) as client:
        login(client, "operator")
        a = client.post("/v1/orgs", json={"name": "First campus"}, headers=keyed()).json()
        b = client.post("/v1/orgs", json={"name": "Second campus"}, headers=keyed()).json()
        request = body(fault="CB_C2_7.tripped")
        request.pop("pack_id")
        request["site_id"] = a["sandbox_site"]["id"]
        inv = client.post(
            f"/v1/orgs/{a['organization']['slug']}/investigations", json=request, headers=keyed()
        )
        assert inv.status_code == 201, inv.text
        yield client, fake, {"a": a, "b": b}, inv.json()


def participant_token(client: TestClient, org: str, inv: dict[str, Any], pid: str) -> str:
    r = client.post(
        f"/v1/orgs/{org}/investigations/{inv['id']}/participants/{pid}/token", headers=keyed()
    )
    assert r.status_code == 200, r.text
    return str(r.json()["token"])


def test_a_link_hears_and_answers_its_question_in_its_workspace(
    workspace_voice: tuple[TestClient, FakeGnaniHttp, dict[str, Any], dict[str, Any]],
) -> None:
    client, _fake, orgs, inv = workspace_voice
    org = orgs["a"]["organization"]["slug"]
    q = inv["pending_question"]
    pid = q["action"]["participant_id"]
    bearer = {"Authorization": f"Bearer {participant_token(client, org, inv, pid)}"}
    client.cookies.clear()  # only the link from here on

    audio = client.get(
        f"/v1/orgs/{org}/investigations/{inv['id']}/questions/{q['id']}/audio", headers=bearer
    )
    assert audio.status_code == 200, audio.text
    assert audio.content[:4] == b"RIFF"

    answered = client.post(
        f"/v1/orgs/{org}/investigations/{inv['id']}/answers/voice",
        data={"question_id": q["id"], "participant_id": pid},
        files={"audio": ("answer.wav", wav(1.0), "audio/wav")},
        headers={**bearer, **keyed()},
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["result"]["observation"]["modality"] == "voice"

    other = orgs["b"]["organization"]["slug"]
    elsewhere = client.get(
        f"/v1/orgs/{other}/investigations/{inv['id']}/questions/{q['id']}/audio", headers=bearer
    )
    assert elsewhere.status_code == 404


def test_a_socket_opened_under_another_workspace_is_refused(
    workspace_voice: tuple[TestClient, FakeGnaniHttp, dict[str, Any], dict[str, Any]],
) -> None:
    client, fake, orgs, inv = workspace_voice
    org = orgs["a"]["organization"]["slug"]
    q = inv["pending_question"]
    pid = q["action"]["participant_id"]
    tok = participant_token(client, org, inv, pid)
    calls = len(fake.calls)
    other_id = orgs["b"]["organization"]["id"]
    for path in (
        f"/v1/orgs/{other_id}/investigations/{inv['id']}/questions/{q['id']}/media",
        f"/v1/orgs/{other_id}/investigations/{inv['id']}/participants/{pid}/call",
    ):
        with client.websocket_connect(path) as ws:
            ws.send_text(json.dumps({"type": "start", "token": tok}))
            code = None
            while code is None:
                msg = ws.receive()
                if msg["type"] == "websocket.close":
                    code = msg.get("code")
        assert code == 4403, path
    assert len(fake.calls) == calls  # nothing reached Gnani
