"""Voice turns in an investigation, with Gnani mocked at the HTTP layer (no credits)."""

from __future__ import annotations

import asyncio
import io
import json
import os
import wave
from collections.abc import Iterator
from pathlib import Path
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
        self.transcripts: list[str] = []
        """Played first, one per STT request, before falling back to ``transcript``."""
        self.stt_statuses: list[int] = []
        """HTTP statuses for the next STT requests (then 200)."""
        self.calls: list[tuple[str, httpx.Request]] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append((req.url.path, req))
        if req.url.path == "/api/v1/tts/inference":
            return httpx.Response(200, content=wav(0.5, 24000))
        status = self.stt_statuses.pop(0) if self.stt_statuses else 200
        if status != 200:
            return httpx.Response(status, json={"detail": "refused"})
        text = self.transcripts.pop(0) if self.transcripts else self.transcript
        return httpx.Response(
            200,
            json={
                "success": True,
                "request_id": "r1",
                "transcript": text,
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
    # The first decode carries the question context (the second, a check, deliberately not).
    fields = form_fields(next(r for path, r in fake.calls if path == "/stt/v3"))
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


def _voice(client: TestClient, inv: dict[str, Any], who: str = "p_riya") -> dict[str, Any]:
    q = inv["pending_question"]
    r = client.post(
        f"/v1/investigations/{inv['id']}/answers/voice",
        data={"question_id": q["id"], "participant_id": who},
        files={"audio": ("a.wav", wav(1.0), "audio/wav")},
    )
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def test_decision_critical_spoken_answer_is_confirmed(
    voice: tuple[TestClient, FakeGnaniHttp],
) -> None:
    client, fake = voice
    inv = create(client)
    # "NAVA-WiFi dikh hi nahi raha" moves the decision a lot; the independent second decode
    # disagrees, so the person is asked again.
    fake.transcripts = ["NAVA-WiFi dikh hi nahi raha", "connected hai"]
    first = _voice(client, inv)
    state = first["result"]["state"]
    confirm = state["pending_question"]
    assert confirm["kind"] == "confirm"
    assert confirm["action"]["probe_id"] == "wifi_status"
    assert confirm["text"].startswith("Ek baar pakka kar lete hain")  # Riya: Hinglish
    p_before = state["belief"]["map_decision_probability"]
    agreed = _voice(client, {**inv, "pending_question": confirm})  # same reading heard again
    after = agreed["result"]["state"]
    assert after["pending_question"]["kind"] == "probe"  # planning resumes
    assert after["belief"]["map_decision_probability"] > p_before  # discount removed
    events = client.get(f"/v1/investigations/{inv['id']}/events").json()
    confirmed = [e["payload"] for e in events if e["type"] == "ObservationConfirmed"]
    assert confirmed[-1]["agreed"] is True


def test_contradicted_confirmation_discards_the_misheard_answer(
    voice: tuple[TestClient, FakeGnaniHttp],
) -> None:
    client, fake = voice
    inv = create(client)
    fake.transcripts = ["NAVA-WiFi dikh hi nahi raha", "connected hai"]  # decodes disagree
    first = _voice(client, inv)
    confirm = first["result"]["state"]["pending_question"]
    fake.transcript = "connected hai"  # the person's second answer disagrees too
    second = _voice(client, {**inv, "pending_question": confirm})
    state = second["result"]["state"]
    original = [o for o in state["observations"] if o["probe_id"] == "wifi_status"]
    assert original[-1]["state"] == "discarded"
    before = {h["id"]: h["probability"] for h in inv["belief"]["hypotheses"]}
    after = {h["id"]: h["probability"] for h in state["belief"]["hypotheses"]}
    assert after == pytest.approx(before)  # back to the belief before the misheard answer
    client.app.state.investigations.evict(inv["id"])  # type: ignore[attr-defined]
    rebuilt = client.get(f"/v1/investigations/{inv['id']}").json()
    assert rebuilt["belief"] == state["belief"]  # replay reproduces the confirmation


def test_typed_answers_are_not_reconfirmed(voice: tuple[TestClient, FakeGnaniHttp]) -> None:
    client, _ = voice
    inv = create(client)
    q = inv["pending_question"]
    r = client.post(
        f"/v1/investigations/{inv['id']}/answers",
        json={
            "question_id": q["id"],
            "participant_id": "p_riya",
            "text": "NAVA-WiFi dikh hi nahi raha",
        },
    )
    assert r.json()["state"]["pending_question"]["kind"] == "probe"


def _stt_requests(fake: FakeGnaniHttp) -> list[httpx.Request]:
    return [r for path, r in fake.calls if path != "/api/v1/tts/inference"]


def test_an_agreeing_second_decode_confirms_without_asking_again(
    voice: tuple[TestClient, FakeGnaniHttp],
) -> None:
    client, fake = voice
    inv = create(client)
    out = _voice(client, inv)  # both decodes read "NAVA-WiFi dikh hi nahi raha"
    state = out["result"]["state"]
    assert state["pending_question"]["kind"] == "probe"  # no "just checking" question
    events = client.get(f"/v1/investigations/{inv['id']}/events").json()
    confirmed = [e["payload"] for e in events if e["type"] == "ObservationConfirmed"]
    assert confirmed[-1]["agreed"] is True
    assert confirmed[-1]["method"] == "second_decode"
    first, second = _stt_requests(fake)[-2:]
    assert b"keyterms" in first.content  # the first decode is steered by the answer words
    assert b"keyterms" not in second.content  # the check is not
    assert b"previous_text" not in second.content
    assert client.get(f"/v1/investigations/{inv['id']}/replay").json()["identical"]


def test_a_failed_second_decode_falls_back_to_asking_again(
    voice: tuple[TestClient, FakeGnaniHttp],
) -> None:
    client, fake = voice
    inv = create(client)
    fake.stt_statuses = [200, 429, 429, 429, 429]  # the check is refused (rate limited)
    out = _voice(client, inv)
    assert out["result"]["state"]["pending_question"]["kind"] == "confirm"
    events = client.get(f"/v1/investigations/{inv['id']}/events").json()
    assert not [e for e in events if e["type"] == "ObservationConfirmed"]


def test_question_audio_survives_a_restart_on_disk(tmp_path: Path) -> None:
    first = QuestionAudioCache(disk_dir=tmp_path)
    first.put("k1", b"RIFF-audio")
    restarted = QuestionAudioCache(disk_dir=tmp_path)  # a new process: memory is empty
    assert restarted.get("k1") == b"RIFF-audio"
    assert QuestionAudioCache().get("k1") is None  # memory-only caches do not share


def test_disk_cache_keeps_the_most_recently_used(tmp_path: Path) -> None:
    cache = QuestionAudioCache(max_entries=1, disk_dir=tmp_path, max_disk_files=2)
    cache.put("a", b"1")
    cache.put("b", b"2")
    os.utime(tmp_path / "a.wav", (1, 1))  # "a" is the oldest
    os.utime(tmp_path / "b.wav", (2, 2))
    cache.put("c", b"3")
    assert sorted(f.stem for f in tmp_path.glob("*.wav")) == ["b", "c"]


def test_restarted_core_replays_question_audio_without_paying(
    migrated_db: str, sim_app: FastAPI, tmp_path: Path
) -> None:
    asyncio.run(truncate_all(migrated_db))
    fake = FakeGnaniHttp()

    def app() -> FastAPI:
        return create_app(
            core_settings(migrated_db, GNANI_API_KEY="k", TTS_CACHE_DIR=str(tmp_path)),
            sim_transport=httpx.ASGITransport(app=sim_app),
            gnani_transport=httpx.MockTransport(fake),
        )

    with TestClient(app()) as client:
        inv = create(client)
        url = f"/v1/investigations/{inv['id']}/questions/{inv['pending_question']['id']}/audio"
        assert client.get(url).headers["X-Audio-Cached"] == "false"
    with TestClient(app()) as again:  # a new process on the same disk cache
        assert again.get(url).headers["X-Audio-Cached"] == "true"
    assert fake.paths().count("/api/v1/tts/inference") == 1
