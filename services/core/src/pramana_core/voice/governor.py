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
* Budget: PostgreSQL serializes reservations and settlement across instances. Abandoned or
  uncertain work remains charged at its reserved worst case. The in-memory ledger is for tests.
"""

from __future__ import annotations

import asyncio
import math
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Database, VoiceUsageRow, acting_as_job, apply_context
from ..errors import ApiError
from ..observability import log

STT_INR_PER_SECOND = 20.0 / 3600.0
TTS_INR_PER_CHAR = 18.0 / 10_000.0
STT_MIN_CHARGE_INR = 0.02
"""Observed on the dashboard (2026-11-04): a 0.03-minute stream (list Rs 0.01) cost Rs 0.02, and
20 STT requests were billed where 17 transcribed. We meter every STT request that reaches Gnani
at no less than this, so the budget errs high, never low."""
_attempts: ContextVar[list[int] | None] = ContextVar("voice_attempts", default=None)


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

    @asynccontextmanager
    async def _locked(self) -> AsyncIterator[AsyncSession]:
        # Never join a request unit of work: reservations must commit before a provider call.
        with acting_as_job("voice-governor"):
            async with self._db._sessions() as session, session.begin():
                await apply_context(session)
                await session.execute(text("select pg_advisory_xact_lock(1894308271)"))
                yield session

    async def reap(self) -> None:
        # Commit expiry separately, even when a subsequent reservation is refused.
        async with self._locked() as session:
            await session.execute(
                text("""
                        with expired as (
                          delete from voice_reservations where expires_at <= now()
                          returning day, service, cost_inr
                        )
                        insert into voice_usage(day, service, units, cost_inr)
                        select greatest(day, (now() at time zone 'UTC')::date), service, 0, cost_inr
                        from expired
                    """)
            )

    async def reserve(self, service: str, cost: float, limits: GovernorLimits) -> uuid.UUID:
        await self.reap()
        reservation = uuid.uuid4()
        async with self._locked() as session:
            spent = (
                await session.execute(
                    text("""
                select coalesce((select sum(cost_inr) from voice_usage
                    where day = (now() at time zone 'UTC')::date), 0)
                  + coalesce((select sum(cost_inr) from voice_reservations), 0)
            """)
                )
            ).scalar_one()
            if float(spent) + cost > limits.daily_budget_inr + 1e-9:
                raise ApiError(429, "VOICE_BUDGET_EXCEEDED", "daily voice budget would be exceeded")
            stream = service == "stt_stream"
            active = (
                await session.execute(
                    text("""
                select count(*) from voice_reservations
                where (service = 'stt_stream') = :stream
            """),
                    {"stream": stream},
                )
            ).scalar_one()
            cap = limits.max_streams if stream else limits.rest_max_inflight
            if active >= cap:
                raise ApiError(
                    429,
                    "VOICE_TOO_MANY_STREAMS" if stream else "VOICE_BUSY",
                    "voice capacity is full",
                )
            await session.execute(
                text("""
                insert into voice_reservations(id, day, service, cost_inr, expires_at)
                values (:id, (now() at time zone 'UTC')::date, :service, :cost,
                        now() + interval '1 hour')
            """),
                {"id": reservation, "service": service, "cost": cost},
            )
        return reservation

    async def settle(self, reservation: uuid.UUID, units: float, cost: float) -> None:
        await self.reap()
        async with self._locked() as session:
            row = (
                await session.execute(
                    text("""
                delete from voice_reservations where id = :id returning day, service, cost_inr
            """),
                    {"id": reservation},
                )
            ).first()
            if row is not None:
                await session.execute(
                    text("""
                    insert into voice_usage(day, service, units, cost_inr)
                    values (greatest(:day, (now() at time zone 'UTC')::date),
                            :service, :units, :cost)
                """),
                    {"day": row.day, "service": row.service, "units": units, "cost": cost},
                )

    async def pace(self, service: str, limit: int, max_wait_s: float) -> None:
        deadline = time.monotonic() + max_wait_s
        while True:
            async with self._locked() as session:
                await session.execute(
                    text(
                        "delete from voice_rate_events "
                        "where created_at <= now() - interval '60 seconds'"
                    )
                )
                row = (
                    await session.execute(
                        text("""
                    select count(*),
                      extract(epoch from (min(created_at) + interval '60 seconds' - now()))
                    from voice_rate_events where service = :service
                """),
                        {"service": service},
                    )
                ).one()
                if row[0] < limit:
                    await session.execute(
                        text("insert into voice_rate_events(id, service) values (:id, :service)"),
                        {"id": uuid.uuid4(), "service": service},
                    )
                    return
                wait = max(float(row[1] or 0), 0.01)
            if time.monotonic() + wait > deadline:
                raise ApiError(429, "VOICE_RATE_LIMITED_LOCAL", "voice rate limit reached")
            await asyncio.sleep(wait)

    async def status(self) -> dict[str, object]:
        await self.reap()
        async with self._locked() as session:
            counts = (
                await session.execute(
                    text("""
                    select service, count(*) from voice_rate_events
                    where created_at > now() - interval '60 seconds' group by service
                """)
                )
            ).all()
            row = (
                await session.execute(
                    text("""
                    select count(*) filter (where service = 'stt_stream'),
                           coalesce(sum(cost_inr), 0)
                    from voice_reservations
                """)
                )
            ).one()
        used: dict[str, int] = {str(service): int(count) for service, count in counts}
        return {
            "window_used": {"stt_rest": used.get("stt_rest", 0), "tts": used.get("tts", 0)},
            "open_streams": row[0],
            "reserved_inr": float(row[1]),
        }

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
        self._streams = asyncio.Semaphore(limits.max_streams)
        self._open_streams = 0
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
        if isinstance(self.ledger, DbLedger):
            limit = (
                self.limits.stt_rest_per_min if service == "stt_rest" else self.limits.tts_per_min
            )
            await self.ledger.pace(service, limit, self.limits.max_wait_s)
            attempts = _attempts.get()
            if attempts is not None:
                attempts[0] += 1
            return
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
        if isinstance(self.ledger, DbLedger):
            # Up to four provider attempts can be billed. Preserve the full reservation on
            # uncertainty, including cancellation or a failed settlement transaction.
            worst = est_cost * 4
            deadline = time.monotonic() + self.limits.max_wait_s
            while True:
                try:
                    reservation = await self.ledger.reserve(service, worst, self.limits)
                    break
                except ApiError as exc:
                    if exc.code != "VOICE_BUSY" or time.monotonic() >= deadline:
                        raise
                    await asyncio.sleep(min(0.05, max(0, deadline - time.monotonic())))
            actual = [est_units]
            attempts = [0]
            token = _attempts.set(attempts)
            ok = False
            try:
                async with asyncio.timeout(3500):
                    yield actual
                ok = True
            finally:
                _attempts.reset(token)
                units = actual[0]
                cost = stt_cost(units) if service == "stt_rest" else tts_cost(int(units))
                cost = cost * max(1, attempts[0]) if ok else worst
                try:
                    await asyncio.shield(self.ledger.settle(reservation, units, cost))
                except Exception:
                    log.exception("voice_usage_settlement_failed", service=service)
            return
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
        if isinstance(self.ledger, DbLedger):
            worst = stt_cost(self.limits.max_stream_s)
            reservation = await self.ledger.reserve("stt_stream", worst, self.limits)
            usage = [0.0, 0.0]
            ok = False
            try:
                async with asyncio.timeout(min(self.limits.max_stream_s, 3500)):
                    yield usage
                ok = True
            finally:
                seconds, attempted = usage[0], usage[1] > 0
                cost = (
                    stt_cost(seconds) if seconds > 0 else (STT_MIN_CHARGE_INR if attempted else 0)
                )
                if not ok:
                    cost = worst
                try:
                    await asyncio.shield(self.ledger.settle(reservation, seconds, cost))
                except Exception:
                    log.exception("voice_usage_settlement_failed", service="stt_stream")
            return
        if self._streams.locked():
            raise ApiError(
                429,
                "VOICE_TOO_MANY_STREAMS",
                f"{self.limits.max_streams} realtime sessions already open",
            )
        worst = stt_cost(self.limits.max_stream_s)
        await self._reserve(worst)
        await self._streams.acquire()
        self._open_streams += 1
        usage = [0.0, 0.0]
        try:
            yield usage
        finally:
            self._open_streams -= 1
            self._streams.release()
            seconds, attempted = usage[0], usage[1] > 0
            cost = stt_cost(seconds) if seconds > 0 else (STT_MIN_CHARGE_INR if attempted else 0)
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
        }

    async def shared_status(self) -> dict[str, object]:
        status = self.status()
        if isinstance(self.ledger, DbLedger):
            status.update(await self.ledger.status())
        return status
