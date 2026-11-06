"""Voice bot call lifecycle behavior."""

from __future__ import annotations

import argparse
import asyncio
import json

import pytest
import voice_bot_run
from voice_bot_common import CallSocketMetrics
from voice_bot_run import Run


class ScenarioResponse:
    def __init__(self, value: str | None = None) -> None:
        self.value = value

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return {"value": self.value or ""}


class RacingSimulator:
    def __init__(self) -> None:
        self.location: dict[str, str] = {}

    async def post(self, path: str, *, json: dict[str, str], headers: dict[str, str]):
        scenario_id = path.split("/")[4]
        if path.endswith("/move"):
            self.location[scenario_id] = json["to"]
            await asyncio.sleep(0)
            return ScenarioResponse()
        await asyncio.sleep(0)
        return ScenarioResponse(self.location[scenario_id])


@pytest.mark.asyncio
async def test_observations_serialize_move_and_observe_for_one_scenario() -> None:
    run = Run.__new__(Run)
    run.tokens = {"p_riya": {"token": "token", "scenario_id": "scenario-1"}}
    run.sim = RacingSimulator()
    run.observe_locks = {}
    run.location_by_scenario = {}

    values = await asyncio.gather(
        run.observe("p_riya", {"requires_move": True, "location_id": "loc-a", "probe_id": "a"}),
        run.observe("p_riya", {"requires_move": True, "location_id": "loc-b", "probe_id": "b"}),
    )

    assert values == ["loc-a", "loc-b"]


@pytest.mark.asyncio
async def test_observation_repositions_after_another_action_moved_the_scenario() -> None:
    run = Run.__new__(Run)
    run.tokens = {"p_riya": {"token": "token", "scenario_id": "scenario-1"}}
    run.sim = RacingSimulator()
    run.observe_locks = {}
    run.location_by_scenario = {}

    first = await run.observe(
        "p_riya", {"requires_move": True, "location_id": "loc-b", "probe_id": "b"}
    )
    second = await run.observe(
        "p_riya", {"requires_move": False, "location_id": "loc-a", "probe_id": "a"}
    )

    assert first == "loc-b"
    assert second == "loc-a"


@pytest.mark.asyncio
async def test_turn_task_exception_is_retained_for_the_run() -> None:
    run = Run.__new__(Run)
    run.tasks = set()
    run.task_errors = []

    async def fail() -> None:
        raise RuntimeError("observation failed")

    task = asyncio.create_task(fail())
    run.tasks.add(task)
    task.add_done_callback(run._turn_task_done)
    with pytest.raises(RuntimeError, match="observation failed"):
        await run._finish_turn_tasks()

    assert run.tasks == set()
    assert len(run.task_errors) == 1
    assert str(run.task_errors[0]) == "observation failed"


class StubWebSocket:
    def __init__(self) -> None:
        self.messages = iter(
            (
                {"type": "ringing", "call_session_id": "call-1"},
                {"type": "consent_request"},
                {"type": "idle"},
                {"type": "call_end", "reason": "nothing more to ask"},
            )
        )
        self.sent: list[dict[str, str]] = []
        self.close_code = 1000
        self.close_reason = ""

    async def __aenter__(self) -> StubWebSocket:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def __aiter__(self) -> StubWebSocket:
        return self

    async def __anext__(self) -> str:
        try:
            message = next(self.messages)
        except StopIteration:
            raise StopAsyncIteration from None
        return json.dumps(message)

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))


@pytest.mark.asyncio
async def test_idle_probe_keeps_call_open_until_server_ends_it(monkeypatch) -> None:
    ws = StubWebSocket()
    monkeypatch.setattr(voice_bot_run.websockets, "connect", lambda *_args, **_kwargs: ws)
    run = Run.__new__(Run)
    run.args = argparse.Namespace(
        core="http://127.0.0.1:8210",
        play=False,
        silent_first=False,
    )
    run.inv = {"id": "inv-1"}
    run.tokens = {"p_riya": {"token": "participant-token"}}
    run.call_metrics = CallSocketMetrics()
    run.call_closes = []
    run.log = []
    run.socket_event_log = None
    run.silent_pid = None
    run.idle_probe_pid = "p_riya"
    run.idle_probe_complete = False
    run.idle_heartbeats = 0

    reason = await run.call("p_riya", "hi")

    assert reason == "nothing more to ask"
    assert run.idle_probe_complete is True
    assert run.idle_heartbeats == 1
    assert all(message.get("type") != "stop" for message in ws.sent)
