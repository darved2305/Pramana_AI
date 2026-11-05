"""The participant page's voice path with sign-in enforced: the join-link token is enough, and
nothing is sent to Gnani for a caller who may not answer (fake Gnani; no credits)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import httpx
import pytest
from auth_testkit import AUTO, AUTOMATION_KEY
from core_testkit import body, core_settings, truncate_all
from fastapi import FastAPI
from fastapi.testclient import TestClient
from test_voice_turns import FakeGnaniHttp, wav

from pramana_core.main import create_app

pytestmark = pytest.mark.db


@pytest.fixture
def secure_voice(migrated_db: str, sim_app: FastAPI) -> Iterator[tuple[TestClient, FakeGnaniHttp]]:
    asyncio.run(truncate_all(migrated_db))
    fake = FakeGnaniHttp()
    app = create_app(
        core_settings(
            migrated_db, GNANI_API_KEY="k", AUTH_REQUIRED=True, CORE_AUTOMATION_KEY=AUTOMATION_KEY
        ),
        sim_transport=httpx.ASGITransport(app=sim_app),
        gnani_transport=httpx.MockTransport(fake),
    )
    with TestClient(app) as client:
        yield client, fake


def test_participant_answers_by_voice_with_their_join_token(
    secure_voice: tuple[TestClient, FakeGnaniHttp],
) -> None:
    client, fake = secure_voice
    inv = client.post("/v1/investigations", json=body(fault="CB_C2_7.tripped"), headers=AUTO)
    assert inv.status_code == 201, inv.text
    state = inv.json()
    q = state["pending_question"]
    pid = q["action"]["participant_id"]
    assert pid == "p_riya"
    tokens = {
        p: client.post(
            f"/v1/investigations/{state['id']}/participants/{p}/token", headers=AUTO
        ).json()["token"]
        for p in ("p_riya", "p_mahesh")
    }
    audio_url = f"/v1/investigations/{state['id']}/questions/{q['id']}/audio"
    answer_url = f"/v1/investigations/{state['id']}/answers/voice"
    form = {"question_id": q["id"], "participant_id": pid}

    # Anonymous and the wrong participant are refused before any Gnani call.
    assert client.get(audio_url).status_code == 401
    wrong = {"Authorization": f"Bearer {tokens['p_mahesh']}"}
    assert client.get(audio_url, headers=wrong).status_code == 403
    r = client.post(
        answer_url, data=form, files={"audio": ("a.wav", wav(1.0), "audio/wav")}, headers=wrong
    )
    assert r.status_code == 403
    assert fake.calls == []

    mine = {"Authorization": f"Bearer {tokens['p_riya']}"}
    spoken = client.get(audio_url, headers=mine)
    assert spoken.status_code == 200
    assert spoken.headers["content-type"] == "audio/wav"
    r = client.post(
        answer_url, data=form, files={"audio": ("a.wav", wav(1.2), "audio/wav")}, headers=mine
    )
    assert r.status_code == 200, r.text
    obs = r.json()["result"]["observation"]
    assert (obs["outcome"], obs["modality"]) == ("no_network", "voice")
    # Question audio, the answer, and the independent check of a decision-critical answer.
    # Uncached audio is streamed first (Timbre SSE); this double answers that path with a plain
    # WAV, so the core falls back to one REST WAV, as it would if streaming were unavailable.
    assert fake.paths() == ["/api/v1/tts/sse", "/api/v1/tts/inference", "/stt/v3", "/stt/v3"]
