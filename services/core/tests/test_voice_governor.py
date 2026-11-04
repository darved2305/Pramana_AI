"""Usage guards: rate windows, concurrency caps and the daily budget (no network)."""

from __future__ import annotations

import asyncio
import io
import time
import wave
from typing import Any

import httpx
import pytest
from fake_gnani import FakeGnani

from pramana_core.db import Database, make_engine
from pramana_core.errors import ApiError
from pramana_core.voice import gnani as gmod
from pramana_core.voice.gnani import GnaniClient
from pramana_core.voice.governor import (
    DbLedger,
    GovernorLimits,
    MemoryLedger,
    RateWindow,
    VoiceGovernor,
    stt_cost,
    tts_cost,
)


def wav(seconds: float) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(seconds * 16000))
    return buf.getvalue()


def ok_tts(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=wav(0.2))


def client(handler: Any, **limits: Any) -> tuple[GnaniClient, MemoryLedger]:
    ledger = MemoryLedger()
    gov = VoiceGovernor(GovernorLimits(**limits), ledger)
    g = GnaniClient(
        "k", "https://api.vachana.ai", 5, governor=gov, transport=httpx.MockTransport(handler)
    )
    return g, ledger


def test_prices_match_the_account_price_list() -> None:
    assert stt_cost(3600) == pytest.approx(20.0)  # Rs 20 per audio hour
    assert tts_cost(10_000) == pytest.approx(18.0)  # Rs 18 per 10,000 characters
    # Observed debit on the Gnani dashboard: 28 characters cost Rs 0.06 (rounded up per request)
    assert tts_cost(28) == pytest.approx(0.06)
    assert stt_cost(2.0) == pytest.approx(0.02)  # Rs 0.0111 rounds up to one paisa more


async def test_rate_window_refuses_or_waits_for_a_free_slot() -> None:
    w = RateWindow("t", 2, window_s=0.3)
    await w.acquire(1)
    await w.acquire(1)
    with pytest.raises(ApiError) as exc:  # window full and unwilling to wait long enough
        await w.acquire(0.01)
    assert exc.value.code == "VOICE_RATE_LIMITED_LOCAL"
    start = time.monotonic()
    await w.acquire(1)  # waits until the oldest slot leaves the window
    assert time.monotonic() - start >= 0.25


async def test_tts_over_the_per_minute_cap_is_refused_locally() -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return ok_tts(req)

    g, _ = client(handler, tts_per_min=3, max_wait_s=0.01)
    for _ in range(3):
        await g.synthesize("hello", language="en-IN")
    with pytest.raises(ApiError) as exc:
        await g.synthesize("hello", language="en-IN")
    assert exc.value.code == "VOICE_RATE_LIMITED_LOCAL"
    assert calls == 3  # the fourth request never reached Gnani
    await g.aclose()


async def test_budget_is_checked_before_sending() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call Gnani when over budget")

    g, ledger = client(handler, daily_budget_inr=0.05)
    with pytest.raises(ApiError) as exc:
        await g.synthesize("x" * 100, language="en-IN")  # Rs 0.18 > Rs 0.05
    assert exc.value.code == "VOICE_BUDGET_EXCEEDED"
    assert ledger.rows == []
    await g.aclose()


async def test_successful_calls_are_metered_failed_calls_are_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gmod, "RETRY_BACKOFF_S", (0.0, 0.0, 0.0))
    g, ledger = client(ok_tts)
    await g.synthesize("नमस्ते", language="hi-IN")
    assert ledger.rows[-1][1:3] == ("tts", 6)
    assert ledger.rows[-1][3] == pytest.approx(tts_cost(6))

    g2, ledger2 = client(lambda _: httpx.Response(401))
    with pytest.raises(ApiError):
        await g2.synthesize("hello", language="en-IN")
    assert ledger2.rows == []

    g3, ledger3 = client(
        lambda _: httpx.Response(
            200, json={"success": True, "request_id": "r", "transcript": "haan"}
        )
    )
    await g3.transcribe(wav(2.0), "a.wav", ["hi-IN"])
    assert ledger3.rows[-1][1:3] == ("stt_rest", pytest.approx(2.0))
    for c in (g, g2, g3):
        await c.aclose()


async def test_retries_consume_rate_slots(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gmod, "RETRY_BACKOFF_S", (0.0, 0.0, 0.0))
    g, _ = client(lambda _: httpx.Response(429))
    with pytest.raises(ApiError):
        await g.synthesize("hello", language="en-IN")
    assert g.governor.tts.used() == 4  # first attempt + three retries
    await g.aclose()


async def test_rest_calls_in_flight_are_capped() -> None:
    active = peak = 0

    async def handler(req: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.05)
        active -= 1
        return ok_tts(req)

    g, _ = client(handler, rest_max_inflight=2)
    await asyncio.gather(*[g.synthesize("hi", language="en-IN") for _ in range(6)])
    assert peak == 2
    await g.aclose()


async def test_stream_slots_are_capped_and_metered() -> None:
    fake = FakeGnani().start()
    ledger = MemoryLedger()
    g = GnaniClient(
        "k", fake.base_url, 5, governor=VoiceGovernor(GovernorLimits(max_streams=1), ledger)
    )
    async with g.stream(["hi-IN"]) as s:
        await s.send_pcm(b"\x00\x00" * 16000)  # one second of audio
        with pytest.raises(ApiError) as exc:
            async with g.stream(["hi-IN"]):
                pass
        assert exc.value.code == "VOICE_TOO_MANY_STREAMS"
    service, seconds = ledger.rows[-1][1], ledger.rows[-1][2]
    assert service == "stt_stream"
    assert seconds == pytest.approx(31 * 1024 / 32000)  # whole 1,024-byte frames sent
    async with g.stream(["hi-IN"]):  # the slot was released
        pass
    await g.aclose()
    fake.stop()


async def test_stream_refused_when_worst_case_exceeds_budget() -> None:
    gov = VoiceGovernor(GovernorLimits(daily_budget_inr=1.0, max_stream_s=300), MemoryLedger())
    g = GnaniClient("k", "http://127.0.0.1:1", 1, governor=gov)
    with pytest.raises(ApiError) as exc:  # 300 s = Rs 1.67 worst case
        async with g.stream(["hi-IN"]):
            pass
    assert exc.value.code == "VOICE_BUDGET_EXCEEDED"
    await g.aclose()


@pytest.mark.db
async def test_db_ledger_persists_across_instances(migrated_db: str) -> None:
    from core_testkit import core_settings

    db = Database(make_engine(core_settings(migrated_db)))
    async with db.transaction() as s:
        await s.execute(__import__("sqlalchemy").text("delete from voice_usage"))
    await DbLedger(db).record("tts", 100, tts_cost(100))
    assert await DbLedger(db).spent_today() == pytest.approx(0.18)  # 100 chars = Rs 0.18 exact
    summary = await DbLedger(db).by_service_today()
    assert summary["tts"]["requests"] == 1
    await db.dispose()
