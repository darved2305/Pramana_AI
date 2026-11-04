"""Event push channel (SSE) against a real uvicorn server and the real database."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
from core_testkit import body, core_settings, truncate_all
from fastapi import FastAPI
from fastapi.testclient import TestClient
from live_server import Sse, read_sse, serve
from participant_bot import answer_pending

from pramana_core.main import create_app
from pramana_core.runtime.broadcast import EventBroadcaster
from pramana_core.runtime.stream import EventStreamResponse, event_stream, sse

pytestmark = pytest.mark.db

TIMEOUT = httpx.Timeout(10.0)


class Live:
    def __init__(self, url: str, app: FastAPI, sim: TestClient) -> None:
        self.url, self.app, self.sim = url, app, sim
        self.http = httpx.Client(base_url=url, timeout=TIMEOUT)

    def create(self) -> dict[str, Any]:
        r = self.http.post("/v1/investigations", json=body(fault="CB_C2_7.tripped"))
        assert r.status_code == 201, r.text
        out: dict[str, Any] = r.json()
        return out

    def polled(self, inv_id: str) -> list[dict[str, Any]]:
        r = self.http.get(f"/v1/investigations/{inv_id}/events", params={"limit": 500})
        out: list[dict[str, Any]] = r.json()
        return out

    def answer(self, state: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = answer_pending(self.http, self.sim, state)["state"]  # type: ignore[arg-type]
        return out

    def subscribers(self, inv_id: str) -> int:
        b: EventBroadcaster = self.app.state.broadcaster
        return b.count(inv_id)


@pytest.fixture
def live(migrated_db: str, sim_app: FastAPI) -> Iterator[Live]:
    asyncio.run(truncate_all(migrated_db))
    settings = core_settings(
        migrated_db,
        EVENT_STREAM_HEARTBEAT_S=0.3,
        EVENT_STREAM_MAX_S=60,
        EVENT_STREAM_STALL_S=2,
    )
    app = create_app(settings, sim_transport=httpx.ASGITransport(app=sim_app))
    with serve(app) as url:
        live = Live(url, app, TestClient(sim_app))
        yield live
        live.http.close()


def _until(it: Iterator[Sse], pred: Any, limit: int = 500) -> list[Sse]:
    out = []
    for _ in range(limit):
        msg = next(it)
        out.append(msg)
        if pred(msg):
            return out
    raise AssertionError("condition not met")


def _log(msgs: list[Sse]) -> list[int]:
    return [m.id for m in msgs if m.event == "message" and m.id is not None]


def test_stream_backfills_then_follows_live_commits(live: Live) -> None:
    state = live.create()
    inv = state["id"]
    head = live.polled(inv)[-1]["seq"]
    with live.http.stream("GET", f"/v1/investigations/{inv}/stream") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        assert "no-transform" in r.headers["cache-control"]
        it = read_sse(r)
        got = _until(it, lambda m: m.id == head)
        ready = next(m for m in got if m.event == "ready")
        assert ready.data == {"after_seq": 0, "head_seq": head}
        state = live.answer(state)  # commits while the stream is open
        new_head = live.polled(inv)[-1]["seq"]
        got += _until(it, lambda m: m.id == new_head)
    polled = live.polled(inv)
    assert _log(got) == [e["seq"] for e in polled]
    first = next(m for m in got if m.event == "message")
    assert first.data == polled[0]  # identical envelope to the polling endpoint


def test_reconnect_with_last_event_id_has_no_gaps_or_duplicates(live: Live) -> None:
    state = live.create()
    inv = state["id"]
    seen: list[int] = []
    with live.http.stream("GET", f"/v1/investigations/{inv}/stream") as r:
        it = read_sse(r)
        msgs = _until(it, lambda m: m.event == "message")
        seen += _log(msgs)
    # Disconnected mid-backfill. Two more commits happen while the client is away.
    state = live.answer(state)
    state = live.answer(state)
    head = live.polled(inv)[-1]["seq"]
    headers = {"Last-Event-ID": str(seen[-1])}
    # The browser resends the original URL (after_seq=0) plus Last-Event-ID: the later wins.
    with live.http.stream(
        "GET", f"/v1/investigations/{inv}/stream", params={"after_seq": 0}, headers=headers
    ) as r:
        it = read_sse(r)
        msgs = _until(it, lambda m: m.id == head)
        assert next(m for m in msgs if m.event == "ready").data["after_seq"] == seen[-1]
        seen += _log(msgs)
    assert seen == [e["seq"] for e in live.polled(inv)]
    assert len(seen) == len(set(seen))


def test_resume_from_after_seq_skips_what_was_seen(live: Live) -> None:
    inv = live.create()["id"]
    seqs = [e["seq"] for e in live.polled(inv)]
    mid = seqs[len(seqs) // 2]
    with live.http.stream(
        "GET", f"/v1/investigations/{inv}/stream", params={"after_seq": mid}
    ) as r:
        msgs = _until(read_sse(r), lambda m: m.id == seqs[-1])
    assert _log(msgs) == [s for s in seqs if s > mid]


def test_position_ahead_of_the_log_resets_and_replays_from_the_start(live: Live) -> None:
    inv = live.create()["id"]
    seqs = [e["seq"] for e in live.polled(inv)]
    with live.http.stream(
        "GET", f"/v1/investigations/{inv}/stream", params={"after_seq": seqs[-1] + 1000}
    ) as r:
        msgs = _until(read_sse(r), lambda m: m.id == seqs[-1])
    reset = next(m for m in msgs if m.event == "reset")
    assert reset.data == {"reason": "after_seq_ahead", "head_seq": seqs[-1]}
    assert _log(msgs) == seqs


def test_unknown_investigation_is_404_before_streaming(live: Live) -> None:
    r = live.http.get("/v1/investigations/inv_missing/stream")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"
    assert live.subscribers("inv_missing") == 0


def test_idle_stream_sends_heartbeats(live: Live) -> None:
    inv = live.create()["id"]
    head = live.polled(inv)[-1]["seq"]
    with live.http.stream("GET", f"/v1/investigations/{inv}/stream") as r:
        it = read_sse(r)
        _until(it, lambda m: m.id == head)
        started = time.monotonic()
        ping = next(it)
        assert ping.event == "comment"
        assert ping.data == "ping"
        assert time.monotonic() - started < 3


def test_stream_ends_with_bye_after_max_duration(live: Live) -> None:
    live.app.state.settings.event_stream_max_s = 0.5
    inv = live.create()["id"]
    head = live.polled(inv)[-1]["seq"]
    with live.http.stream("GET", f"/v1/investigations/{inv}/stream") as r:
        msgs = _until(read_sse(r), lambda m: m.event == "bye")
    assert msgs[-1].data == {"reason": "max_duration", "resume_after_seq": head}


def test_disconnect_releases_the_subscription(live: Live) -> None:
    inv = live.create()["id"]
    with live.http.stream("GET", f"/v1/investigations/{inv}/stream") as r:
        it = read_sse(r)
        next(it)
        assert live.subscribers(inv) == 1
    deadline = time.monotonic() + 5
    while live.subscribers(inv) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert live.subscribers(inv) == 0


def test_two_streams_see_the_same_sequence(live: Live) -> None:
    state = live.create()
    inv = state["id"]
    url = f"/v1/investigations/{inv}/stream"
    other = httpx.Client(base_url=live.url, timeout=TIMEOUT)
    with live.http.stream("GET", url) as a, other.stream("GET", url) as b:
        ia, ib = read_sse(a), read_sse(b)
        head = live.polled(inv)[-1]["seq"]
        got_a, got_b = _until(ia, lambda m: m.id == head), _until(ib, lambda m: m.id == head)
        live.answer(state)
        head = live.polled(inv)[-1]["seq"]
        got_a += _until(ia, lambda m: m.id == head)
        got_b += _until(ib, lambda m: m.id == head)
    other.close()
    assert _log(got_a) == _log(got_b) == [e["seq"] for e in live.polled(inv)]


def test_subscriber_cap_is_enforced(live: Live) -> None:
    live.app.state.broadcaster.max_per_investigation = 1
    inv = live.create()["id"]
    with live.http.stream("GET", f"/v1/investigations/{inv}/stream") as r:
        it = read_sse(r)  # keep a reference: a discarded iterator closes the response
        next(it)
        assert live.subscribers(inv) == 1
        second = httpx.get(f"{live.url}/v1/investigations/{inv}/stream", timeout=TIMEOUT)
        assert second.status_code == 429
        assert second.json()["error"]["code"] == "TOO_MANY_SUBSCRIBERS"
        next(it)  # the first stream is unaffected


def test_polling_still_works(live: Live) -> None:
    inv = live.create()["id"]
    events = live.polled(inv)
    assert events[0]["type"] == "InvestigationCreated"
    tail = live.http.get(
        f"/v1/investigations/{inv}/events", params={"after_seq": events[-2]["seq"]}
    ).json()
    assert [e["seq"] for e in tail] == [events[-1]["seq"]]


# -- units: no database ----------------------------------------------------------------------


async def test_publish_never_blocks_and_coalesces() -> None:
    b = EventBroadcaster()
    sub = b.subscribe("inv_x")
    for _ in range(10_000):  # a subscriber that never reads holds no backlog
        b.publish(["inv_x", "inv_other"])
    assert await sub.wait(0.01) is True
    assert await sub.wait(0.01) is False  # ten thousand commits, one wake-up
    sub.close()
    assert b.count() == 0


async def test_shutdown_ends_open_streams_with_bye() -> None:
    b = EventBroadcaster()
    sub = b.subscribe("inv_x")

    async def fetch(_after: int, _limit: int) -> list[Any]:
        return []

    async def head() -> int:
        return 0

    gen = event_stream(sub, 0, fetch, head, heartbeat_s=30, max_duration_s=600)
    chunks = [await gen.__anext__() for _ in range(2)]  # retry, ready
    assert b"ready" in chunks[1]
    b.close()
    bye = await gen.__anext__()
    assert b"event: bye" in bye
    assert b'"shutdown"' in bye
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()
    assert b.count() == 0


async def test_a_stalled_client_is_dropped_not_waited_on() -> None:
    b = EventBroadcaster()
    sub = b.subscribe("inv_x")

    async def fetch(_after: int, _limit: int) -> list[Any]:
        return []

    async def head() -> int:
        return 0

    gen = event_stream(sub, 0, fetch, head, heartbeat_s=0.05, max_duration_s=600)
    response = EventStreamResponse(gen, stall_s=0.2, on_close=sub.close)
    sent: list[Any] = []

    async def send(message: Any) -> None:
        if message["type"] == "http.response.body" and len(sent) >= 3:
            await asyncio.Event().wait()  # the client stopped reading: blocks forever
        sent.append(message)

    async def receive() -> Any:
        await asyncio.Event().wait()

    started = time.monotonic()
    await asyncio.wait_for(
        response({"type": "http", "asgi": {"spec_version": "2.3"}}, receive, send), 5
    )
    assert time.monotonic() - started < 2
    assert response.stalled
    assert b.count() == 0


def test_sse_encoding_splits_lines() -> None:
    assert sse("a\nb", event="x", id_=3) == b"id: 3\nevent: x\ndata: a\ndata: b\n\n"
