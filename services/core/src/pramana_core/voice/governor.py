"""Guards that keep Gnani usage inside the account's limits and a spending budget.

Account limits (Gnani dashboard pricing page, 2026-11-04): STT REST 60 requests/min, STT
WebSocket 20 concurrent sessions, TTS 60 requests/min. Prices: STT Rs 20 per audio hour, TTS
Rs 18 per 10,000 characters. We run below the limits (defaults: 50/min, 16 sessions) and refuse
work that would exceed a daily budget.

* Rate: a sliding 60-second window per service. A caller waits up to ``max_wait_s`` for a free
  slot, otherwise gets ``429 VOICE_RATE_LIMITED_LOCAL``; we never send a request we expect
  Gnani to reject.
* Concurrency: a fixed pool of stream slots, acquired without waiting (``429
  VOICE_TOO_MANY_STREAMS``), plus a cap on in-flight REST calls.
* Budget: every call is priced *before* it is sent (worst case for streams: the maximum
  session length) and recorded *after* with actual usage, in PostgreSQL so restarts do not
  reset it. Limits are per core process; a multi-process deployment would move the rate
  windows to the database or Redis.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

from sqlalchemy import func, select

from ..db import Database, VoiceUsageRow
from ..errors import ApiError
from ..observability import log

STT_INR_PER_SECOND = 20.0 / 3600.0
TTS_INR_PER_CHAR = 18.0 / 10_000.0
STT_MIN_CHARGE_INR = 0.02
"""Observed on the dashboard (2026-11-04): a 0.03-minute stream (list Rs 0.01) cost Rs 0.02, and
20 STT requests were billed where 17 transcribed. We meter every STT request that reaches Gnani
at no less than this, so the budget errs high, never low."""


def _per_request(raw_inr: float) -> float:
    """Gnani rounds each request up to the next paisa: 28 TTS characters (list price
    Rs 0.0504) were debited Rs 0.06 on 2026-11-04. Meter the same way, never below."""
    return math.ceil(round(raw_inr * 100, 6)) / 100 if raw_inr > 0 else 0.0


def stt_cost(seconds: float) -> float:
    if seconds <= 0:
        return 0.0
    return max(STT_MIN_CHARGE_INR, _per_request(seconds * STT_INR_PER_SECOND))


def tts_cost(chars: int) -> float:
    return _per_request(max(0, chars) * TTS_INR_PER_CHAR)


class RateWindow:
    """At most ``limit`` acquisitions in any 60-second window."""

    def __init__(self, name: str, limit_per_min: int, window_s: float = 60.0) -> None:
        self.name, self.limit, self.window = name, limit_per_min, window_s
        self._stamps: deque[float] = deque()
        self._lock = asyncio.Lock()

    def _prune(self, now: float) -> None:
        while self._stamps and now - self._stamps[0] >= self.window:
            self._stamps.popleft()

    async def acquire(self, max_wait_s: float) -> None:
        deadline = time.monotonic() + max_wait_s
        async with self._lock:
            while True:
                now = time.monotonic()
                self._prune(now)
                if len(self._stamps) < self.limit:
                    self._stamps.append(now)
                    return
                wait = self.window - (now - self._stamps[0])
                if now + wait > deadline:
                    raise ApiError(
                        429,
                        "VOICE_RATE_LIMITED_LOCAL",
                        f"{self.name}: {self.limit}/min reached; retry in {wait:.0f} s",
                    )
                await asyncio.sleep(wait)

    def used(self) -> int:
        self._prune(time.monotonic())
        return len(self._stamps)


class Ledger(Protocol):
    async def spent_today(self) -> float: ...
    async def record(self, service: str, units: float, cost_inr: float) -> None: ...


class DbLedger:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def spent_today(self) -> float:
        async with self._db.read() as s:
            total = (
                await s.execute(
                    select(func.coalesce(func.sum(VoiceUsageRow.cost_inr), 0.0)).where(
                        VoiceUsageRow.day == datetime.now(UTC).date()
                    )
                )
            ).scalar_one()
        return float(total)

    async def record(self, service: str, units: float, cost_inr: float) -> None:
        async with self._db.transaction() as s:
            s.add(
                VoiceUsageRow(
                    day=datetime.now(UTC).date(), service=service, units=units, cost_inr=cost_inr
                )
            )

    async def by_service_today(self) -> dict[str, dict[str, float]]:
        async with self._db.read() as s:
            rows = (
                await s.execute(
                    select(
                        VoiceUsageRow.service,
                        func.count(),
                        func.sum(VoiceUsageRow.units),
                        func.sum(VoiceUsageRow.cost_inr),
                    )
                    .where(VoiceUsageRow.day == datetime.now(UTC).date())
                    .group_by(VoiceUsageRow.service)
                )
            ).all()
        return {
            svc: {"requests": float(n), "units": float(u or 0), "cost_inr": float(c or 0)}
            for svc, n, u, c in rows
        }


class MemoryLedger:
    """For tests: same behaviour as ``DbLedger`` without a database."""

    def __init__(self) -> None:
        self.rows: list[tuple[date, str, float, float]] = []

    async def spent_today(self) -> float:
        today = datetime.now(UTC).date()
        return sum(c for d, _, _, c in self.rows if d == today)

    async def record(self, service: str, units: float, cost_inr: float) -> None:
        self.rows.append((datetime.now(UTC).date(), service, units, cost_inr))


@dataclass(frozen=True)
class GovernorLimits:
    stt_rest_per_min: int = 50
    tts_per_min: int = 50
    max_streams: int = 16
    rest_max_inflight: int = 1
    daily_budget_inr: float = 150.0
    max_wait_s: float = 5.0
    max_stream_s: float = 300.0


class VoiceGovernor:
    def __init__(self, limits: GovernorLimits, ledger: Ledger) -> None:
        self.limits = limits
        self.ledger = ledger
        self.stt_rest = RateWindow("stt_rest", limits.stt_rest_per_min)
        self.tts = RateWindow("tts", limits.tts_per_min)
        self._open_streams = 0
        self._peak_streams = 0
        self._inflight = asyncio.Semaphore(limits.rest_max_inflight)
        self._budget_lock = asyncio.Lock()
        self._reserved = 0.0

    async def _reserve(self, cost: float) -> None:
        async with self._budget_lock:
            spent = await self.ledger.spent_today()
            if spent + self._reserved + cost > self.limits.daily_budget_inr:
                raise ApiError(
                    429,
                    "VOICE_BUDGET_EXCEEDED",
                    f"daily voice budget Rs {self.limits.daily_budget_inr:.2f} would be "
                    f"exceeded (spent Rs {spent:.2f})",
                )
            self._reserved += cost

    async def _settle(self, reserved: float, service: str, units: float, cost: float) -> None:
        async with self._budget_lock:
            self._reserved -= reserved
        if units > 0:
            try:
                await self.ledger.record(service, units, cost)
            except Exception:
                log.exception("voice_usage_record_failed", service=service)

    async def pace(self, service: str) -> None:
        """Take one request slot; call once per HTTP attempt, retries included."""
        window = self.stt_rest if service == "stt_rest" else self.tts
        await window.acquire(self.limits.max_wait_s)

    @asynccontextmanager
    async def rest_call(
        self, service: str, est_units: float, est_cost: float
    ) -> AsyncIterator[list[float]]:
        """Rate-limit, cap in-flight requests, and meter one REST call.

        Yields a one-element list the caller may update with the actual billable units
        (defaults to the estimate). Failed calls are not charged.
        """
        await self._reserve(est_cost)
        actual = [est_units]
        ok = False
        try:
            async with self._inflight:
                yield actual
            ok = True
        finally:
            units = actual[0] if ok else 0.0
            cost = stt_cost(units) if service == "stt_rest" else tts_cost(int(units))
            await self._settle(est_cost, service, units, cost)

    @asynccontextmanager
    async def stream_slot(self) -> AsyncIterator[list[float]]:
        """Hold one realtime session slot; yields ``[audio_seconds_sent, attempted]``.

        A session that reached Gnani is charged at least the STT minimum even if it failed or
        carried no audio (failed sessions appear as billed requests on the dashboard).
        """
        # Check and reserve before the first await. Otherwise concurrent callers can all pass
        # the check while the budget ledger is being read, then queue on the semaphore instead
        # of being refused at the configured provider limit.
        if self._open_streams >= self.limits.max_streams:
            raise ApiError(
                429,
                "VOICE_TOO_MANY_STREAMS",
                f"{self.limits.max_streams} realtime sessions already open",
            )
        self._open_streams += 1
        self._peak_streams = max(self._peak_streams, self._open_streams)
        worst = stt_cost(self.limits.max_stream_s)
        usage = [0.0, 0.0]
        reserved = False
        try:
            await self._reserve(worst)
            reserved = True
            yield usage
        finally:
            self._open_streams -= 1
            if reserved:
                seconds, attempted = usage[0], usage[1] > 0
                cost = stt_cost(seconds) if seconds > 0 else 0
                if seconds <= 0 and attempted:
                    cost = STT_MIN_CHARGE_INR
                billable = max(seconds, 1e-3) if attempted else seconds
                await self._settle(worst, "stt_stream", billable, cost)

    def status(self) -> dict[str, object]:
        return {
            "limits": {
                "stt_rest_per_min": self.limits.stt_rest_per_min,
                "tts_per_min": self.limits.tts_per_min,
                "max_streams": self.limits.max_streams,
                "rest_max_inflight": self.limits.rest_max_inflight,
                "daily_budget_inr": self.limits.daily_budget_inr,
            },
            "window_used": {"stt_rest": self.stt_rest.used(), "tts": self.tts.used()},
            "open_streams": self._open_streams,
            "peak_streams": self._peak_streams,
        }
