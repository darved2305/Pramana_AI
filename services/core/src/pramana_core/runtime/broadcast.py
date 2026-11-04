"""In-process event fan-out (docs/adr/0009-event-push-channel.md).

Writers never block and never hold events in memory on behalf of subscribers. After a
transaction commits, the database announces which investigations it appended events to, and
each subscriber of those investigations gets a *coalescing* wake-up: a flag, not a queue entry.
The subscriber then reads everything after its last ``seq`` from PostgreSQL, the source of truth.

Consequences:

* No gaps or duplicates: the subscriber always asks for ``seq > last_sent`` and per-investigation
  ``seq`` order equals commit order (one writer per investigation, ADR 0003).
* No race between backfill and subscription: subscribe first, then read; a commit that lands in
  between only sets the flag again, and the next read skips anything already sent.
* Bounded memory under slow consumers: the per-subscriber "queue" is one flag, and reads are
  paged. A slow consumer only delays itself.
* Other core processes' commits are not announced here; subscribers also re-check the database
  on every heartbeat, so they converge within one heartbeat interval.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Iterable


class TooManySubscribersError(RuntimeError):
    pass


class Subscription:
    def __init__(self, broadcaster: EventBroadcaster, investigation_id: str) -> None:
        self.investigation_id = investigation_id
        self._broadcaster = broadcaster
        self._wake = asyncio.Event()
        self.closed = False
        """Set when the broadcaster shuts down: the stream should say goodbye and end."""

    def notify(self) -> None:
        self._wake.set()

    async def wait(self, seconds: float) -> bool:
        """Wait for new commits (True) or ``seconds`` (False). Clears the flag.

        A wake-up lost to a timeout race costs nothing: the stream re-reads the log after
        every wait, whether or not it was woken.
        """
        try:
            async with asyncio.timeout(seconds):
                await self._wake.wait()
        except TimeoutError:
            return False
        finally:
            self._wake.clear()
        return True

    def close(self) -> None:
        self._broadcaster._remove(self)

    def __enter__(self) -> Subscription:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


class EventBroadcaster:
    def __init__(self, max_per_investigation: int = 64, max_total: int = 1000) -> None:
        self.max_per_investigation = max_per_investigation
        self.max_total = max_total
        self._subs: dict[str, set[Subscription]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self.published = 0

    def subscribe(self, investigation_id: str) -> Subscription:
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        subs = self._subs.setdefault(investigation_id, set())
        if len(subs) >= self.max_per_investigation or self.count() >= self.max_total:
            if not subs:
                del self._subs[investigation_id]
            raise TooManySubscribersError(investigation_id)
        sub = Subscription(self, investigation_id)
        subs.add(sub)
        return sub

    def _remove(self, sub: Subscription) -> None:
        subs = self._subs.get(sub.investigation_id)
        if subs is not None:
            subs.discard(sub)
            if not subs:
                del self._subs[sub.investigation_id]

    def count(self, investigation_id: str | None = None) -> int:
        if investigation_id is not None:
            return len(self._subs.get(investigation_id, ()))
        return sum(len(s) for s in self._subs.values())

    def publish(self, investigation_ids: Iterable[str]) -> None:
        """Announce committed events. Safe to call from any thread; never blocks, never raises."""
        ids = set(investigation_ids)
        if not ids:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if self._loop is not None and running is not self._loop:
            # A closed loop has nobody listening on it.
            with contextlib.suppress(RuntimeError):
                self._loop.call_soon_threadsafe(self._notify, ids)
        else:
            self._notify(ids)

    def _notify(self, ids: set[str]) -> None:
        for inv in ids:
            for sub in list(self._subs.get(inv, ())):
                sub.notify()
        self.published += 1

    def close(self) -> None:
        """Wake every subscriber so open streams end cleanly (process shutdown)."""
        for subs in list(self._subs.values()):
            for sub in list(subs):
                sub.closed = True
                sub.notify()
