"""Voice turns in an investigation, with Gnani mocked at the HTTP layer (no credits)."""

from __future__ import annotations

import asyncio
import io
import json
import wave
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from core_testkit import body, core_settings, truncate_all
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pramana_core.main import create_app
from pramana_core.voice.conversation import QuestionAudioCache, answer_keyterms
from pramana_domain import load_pack

pytestmark = pytest.mark.db


def wav(seconds: float = 1.0, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(seconds * rate))
    return buf.getvalue()


class FakeGnaniHttp:
    """Records requests; answers TTS with WAV and STT with a configurable transcript."""

    def __init__(self) -> None:
        self.transcript = "NAVA-WiFi dikh hi nahi raha"
        self.calls: list[tuple[str, httpx.Request]] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append((req.url.path, req))
        if req.url.path == "/api/v1/tts/inference":
            return httpx.Response(200, content=wav(0.5, 24000))
        return httpx.Response(
            200,
            json={
                "success": True,
                "request_id": "r1",
                "transcript": self.transcript,
                "model": "prisma-v3.0",
                "detected_language_code": "hi-IN",
                "processing_time": 0.2,
            },
        )

    def paths(self) -> list[str]:
        return [p for p, _ in self.calls]


@pytest.fixture
def voice(migrated_db: str, sim_app: FastAPI) -> Iterator[tuple[TestClient, FakeGnaniHttp]]:
    asyncio.run(truncate_all(migrated_db))
    fake = FakeGnaniHttp()
    app = create_app(
        core_settings(migrated_db, GNANI_API_KEY="k"),
        sim_transport=httpx.ASGITransport(app=sim_app),
        gnani_transport=httpx.MockTransport(fake),
    )
    with TestClient(app) as client:
        yield client, fake


def create(client: TestClient) -> dict[str, Any]:
    r = client.post("/v1/investigations", json=body(fault="CB_C2_7.tripped"))
    assert r.status_code == 201, r.text
    data: dict[str, Any] = r.json()
    return data


def form_fields(req: httpx.Request) -> dict[str, str]:
    text = req.content.decode("utf-8", "replace")
    out = {}
    for part in text.split("--")[1:]:
        if 'name="' in part and "filename=" not in part:
            name = part.split('name="', 1)[1].split('"', 1)[0]
            out[name] = part.split("\r\n\r\n", 1)[1].rsplit("\r\n", 1)[0]
    return out


def test_question_audio_is_spoken_in_the_participants_language_and_cached(
    voice: tuple[TestClient, FakeGnaniHttp],
) -> None:
    client, fake = voice
    inv = create(client)
    q = inv["pending_question"]
    url = f"/v1/investigations/{inv['id']}/questions/{q['id']}/audio"
    first = client.get(url)
    assert first.status_code == 200
    assert first.content[:4] == b"RIFF"
    assert first.headers["X-Audio-Cached"] == "false"
    tts_body = json.loads(fake.calls[-1][1].content)
    assert tts_body["text"] == q["text"]
    assert (tts_body["language"], tts_body["model"]) == ("hi-en", "timbre-v2.5")  # Riya: Hinglish
    second = client.get(url)
    assert second.headers["X-Audio-Cached"] == "true"
    assert fake.paths().count("/api/v1/tts/inference") == 1  # replay costs nothing


def test_voice_answer_uses_question_context_and_updates_the_belief(
    voice: tuple[TestClient, FakeGnaniHttp],
) -> None:
    client, fake = voice
    inv = create(client)
    q = inv["pending_question"]
    r = client.post(
        f"/v1/investigations/{inv['id']}/answers/voice",
        data={"question_id": q["id"], "participant_id": "p_riya"},
        files={"audio": ("answer.wav", wav(1.2), "audio/wav")},
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["stt"]["transcript"] == "NAVA-WiFi dikh hi nahi raha"
    obs = out["result"]["observation"]
    assert (obs["probe_id"], obs["outcome"], obs["modality"]) == (
        "wifi_status",
        "no_network",
        "voice",
    )
    assert obs["transcript"] == "NAVA-WiFi dikh hi nahi raha"
    fields = form_fields(fake.calls[-1][1])
    assert fields["model"] == "prisma-v3.0"
    assert fields["language_code"] == "hi-IN,en-IN"
    assert fields["format"] == "codemix"  # Riya is registered as a code-mixing speaker
    assert fields["previous_text"] == q["text"]
    terms = json.loads(fields["keyterms"])
    assert "dikh hi nahi" in terms
    assert "NAVA-WiFi" in terms
    nxt = out["result"]["state"]["pending_question"]
    assert nxt is not None
    assert nxt["id"] != q["id"]


@pytest.mark.parametrize(
    ("who", "status", "code"),
    [("p_imran", 403, "WRONG_PARTICIPANT")],
)
def test_invalid_voice_answers_are_rejected_before_paying(
    voice: tuple[TestClient, FakeGnaniHttp], who: str, status: int, code: str
) -> None:
    client, fake = voice
    inv = create(client)
    q = inv["pending_question"]
    r = client.post(
        f"/v1/investigations/{inv['id']}/answers/voice",
        data={"question_id": q["id"], "participant_id": who},
        files={"audio": ("a.wav", wav(), "audio/wav")},
    )
    assert r.status_code == status
    assert r.json()["error"]["code"] == code
    assert "/stt/v3" not in fake.paths()


def test_answered_question_cannot_be_answered_or_spoken_again(
    voice: tuple[TestClient, FakeGnaniHttp],
) -> None:
    client, fake = voice
    inv = create(client)
    q = inv["pending_question"]
    client.post(
        f"/v1/investigations/{inv['id']}/answers",
        json={"question_id": q["id"], "participant_id": "p_riya", "outcome": "no_network"},
    )
    stt_before = fake.paths().count("/stt/v3")
    r = client.post(
        f"/v1/investigations/{inv['id']}/answers/voice",
        data={"question_id": q["id"], "participant_id": "p_riya"},
        files={"audio": ("a.wav", wav(), "audio/wav")},
    )
    assert r.status_code == 409
    assert (
        client.get(f"/v1/investigations/{inv['id']}/questions/{q['id']}/audio").status_code == 409
    )
    assert fake.paths().count("/stt/v3") == stt_before


def test_empty_transcript_records_nothing(voice: tuple[TestClient, FakeGnaniHttp]) -> None:
    client, fake = voice
    fake.transcript = ""
    inv = create(client)
    q = inv["pending_question"]
    r = client.post(
        f"/v1/investigations/{inv['id']}/answers/voice",
        data={"question_id": q["id"], "participant_id": "p_riya"},
        files={"audio": ("a.wav", wav(0.3), "audio/wav")},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VOICE_EMPTY_TRANSCRIPT"
    after = client.get(f"/v1/investigations/{inv['id']}").json()
    assert after["pending_question"]["id"] == q["id"]
    assert len(after["observations"]) == len(inv["observations"])


def test_answer_keyterms_cover_the_probe_vocabulary() -> None:
    pack = load_pack("campus_block_c")
    for probe in pack.probes:
        terms = answer_keyterms(pack, probe.id)
        assert 0 < len(terms) <= 200
        assert len(terms) == len(set(terms))
    nvr = answer_keyterms(pack, "nvr_screen")
    assert "बंद" in nvr
    assert "chalu" in nvr


def test_question_audio_cache_is_bounded() -> None:
    cache = QuestionAudioCache(max_entries=2, max_bytes=10)
    cache.put("a", b"1234")
    cache.put("b", b"1234")
    cache.put("c", b"1234")
    assert len(cache) == 2
    assert cache.get("a") is None
    cache.put("big", b"x" * 11)
    assert cache.get("big") is None
