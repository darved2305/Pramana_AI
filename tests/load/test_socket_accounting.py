"""Close and coverage accounting for sustained voice load runs."""

from __future__ import annotations

from load.harness import (
    _call_close_issues,
    _peak_socket_count,
    _provider_close_issues,
    _should_launch_handoff_run,
    _three_call_window,
)


def _client_close(**updates: object) -> dict[str, object]:
    return {
        "call_session_id": "call-1",
        "investigation_id": "inv-1",
        "participant_id": "p_riya",
        "call_end_received": True,
        "call_end_reason": "nothing more to ask",
        "code": 1000,
        "reason": "",
        **updates,
    }


def _core_close(**updates: object) -> dict[str, object]:
    return {
        "call_session_id": "call-1",
        "investigation_id": "inv-1",
        "participant_id": "p_riya",
        "reason": "nothing more to ask",
        "socket_close_initiator": "server",
        "call_end_sent": True,
        "socket_close_code": 1000,
        "socket_close_reason": "",
        **updates,
    }


def test_call_closes_match_call_end_lifecycle_on_both_sides() -> None:
    assert _call_close_issues([_client_close()], [_core_close()]) == []


def test_premature_normal_client_close_is_unexpected() -> None:
    client = _client_close(call_end_received=False, call_end_reason=None)
    core = _core_close(
        reason="participant disconnected",
        socket_close_initiator="participant",
        call_end_sent=False,
    )

    issues = _call_close_issues([client], [core])

    assert issues
    assert any("before call_end" in issue["issue"] for issue in issues)


def test_silent_release_code_is_allowed_only_for_the_designated_silent_call() -> None:
    unintended_client = _client_close(call_end_reason="silent", expected_close_code=1000, code=4408)
    unintended_core = _core_close(reason="silent", socket_close_code=4408)

    unintended_issues = _call_close_issues([unintended_client], [unintended_core])

    assert any(issue["issue"] == "unexpected close code" for issue in unintended_issues)
    designated_client = _client_close(call_end_reason="silent", expected_close_code=4408, code=4408)
    designated_core = _core_close(reason="silent", socket_close_code=4408)
    assert _call_close_issues([designated_client], [designated_core]) == []


def test_timeout_code_and_nonempty_transport_reason_are_unexpected() -> None:
    client = _client_close(code=1006, reason="provider timeout")
    core = _core_close(socket_close_code=1006, socket_close_reason="provider timeout")

    issues = _call_close_issues([client], [core])

    assert any("close code" in issue["issue"] for issue in issues)
    assert any("nonempty close reason" in issue["issue"] for issue in issues)


def test_provider_close_is_correlated_and_reason_checked() -> None:
    server = [{"session_id": "stt-1", "code": 1000, "reason": "unexpected text"}]
    core = [{"session_id": "stt-1", "code": 1000, "reason": ""}]

    issues = _provider_close_issues(server, core, observe_server=True)

    assert any(
        issue["side"] == "provider_server" and issue["issue"] == "nonempty close reason"
        for issue in issues
    )
    assert any(issue["issue"] == "provider close differs between sides" for issue in issues)


def test_three_call_window_measures_handoff_gaps_inside_requested_window() -> None:
    events = [
        {"event": "open", "socket_id": "a", "at_monotonic": 9.0},
        {"event": "open", "socket_id": "b", "at_monotonic": 9.0},
        {"event": "open", "socket_id": "c", "at_monotonic": 9.0},
        {"event": "close", "socket_id": "c", "at_monotonic": 15.0},
        {"event": "open", "socket_id": "d", "at_monotonic": 17.0},
    ]

    window = _three_call_window(events, started_at=10.0, ended_at=20.0)

    assert window["three_call_seconds"] == 8.0
    assert window["under_three_call_seconds"] == 2.0
    assert window["max_handoff_gap_seconds"] == 2.0
    assert window["handoff_gaps"] == [
        {
            "start": 15.0,
            "end": 17.0,
            "duration_seconds": 2.0,
            "reason": "fewer than three participant call sockets were open during a handoff",
        }
    ]


def test_handoff_peak_is_bounded_by_three_three_call_runs() -> None:
    events = [
        {"event": "open", "socket_id": str(index), "at_monotonic": 10.0} for index in range(9)
    ]

    assert _peak_socket_count(events, started_at=10.0, ended_at=20.0) == 9


def test_handoff_replenishes_before_coverage_falls_below_three_calls() -> None:
    assert _should_launch_handoff_run(running_jobs=2, active_call_sockets=2) is True
    assert _should_launch_handoff_run(running_jobs=2, active_call_sockets=3) is True
    assert _should_launch_handoff_run(running_jobs=2, active_call_sockets=5) is True
    assert _should_launch_handoff_run(running_jobs=2, active_call_sockets=6) is False
    assert _should_launch_handoff_run(running_jobs=3, active_call_sockets=0) is False
