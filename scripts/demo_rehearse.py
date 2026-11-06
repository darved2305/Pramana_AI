"""Run a text-mode rehearsal against the core and simulator APIs."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, TextIO

import httpx

try:
    from .core_auth import automation_headers
    from .text_investigation import (
        PEOPLE,
        RehearsalError,
        create_investigation,
        create_request,
        play_pending,
        repair_and_verify,
        reveal_and_replay,
        reveal_summary,
    )
except ImportError:
    from core_auth import automation_headers
    from text_investigation import (
        PEOPLE,
        RehearsalError,
        create_investigation,
        create_request,
        play_pending,
        repair_and_verify,
        reveal_and_replay,
        reveal_summary,
    )

ROOT = Path(__file__).resolve().parents[1]
S1_FAULT = {"faults": [{"component_id": "CB_C2_7", "mode": "tripped"}]}
S2_FAULT = {"faults": [{"component_id": "AP_2A", "mode": "dead"}]}
S7_FAULT = {"faults": [{"component_id": "SW_C2", "mode": "dead"}]}
S2_PEOPLE: list[dict[str, Any]] = [
    {
        **PEOPLE[0],
        "id": "p_neha",
        "display_name": "Neha",
        "location_id": "F2_R210",
        "languages": {"stt_candidates": ["en-IN"], "template_language": "en"},
    },
    {
        **PEOPLE[0],
        "id": "p_aarav",
        "display_name": "Aarav",
        "location_id": "F2_R205",
        "languages": {"stt_candidates": ["en-IN"], "template_language": "en"},
    },
]
S7_PEOPLE: list[dict[str, Any]] = [dict(PEOPLE[0]), dict(PEOPLE[1])]


def scenario_request(scenario: str, *, seed: int) -> dict[str, Any]:
    """Build scenario bodies using the fields sent by the console create form."""
    name = scenario.upper()
    if name == "S1":
        return {
            "pack_id": "campus_block_c",
            "participants": PEOPLE,
            "report": {
                "text": "Floor 3 pe WiFi nahi chal raha, kuch khul nahi raha",
                "reporter_id": "p_riya",
                "affected_location_id": None,
            },
            "scenario": {"seed": seed, "fault": S1_FAULT},
            "max_parallel_calls": 3,
            "presence_checks": False,
        }
    if name == "S2":
        return {
            "pack_id": "campus_block_c",
            "participants": S2_PEOPLE,
            "report": {
                "text": "Wi-Fi is not working in room 210",
                "reporter_id": "p_neha",
                "affected_location_id": None,
            },
            "scenario": {"seed": seed, "fault": S2_FAULT},
            "max_parallel_calls": 1,
            "presence_checks": False,
        }
    if name == "S7":
        return {
            "pack_id": "campus_block_c",
            "participants": S7_PEOPLE,
            "report": {
                "text": "Floor 3 pe WiFi nahi chal raha, kuch khul nahi raha",
                "reporter_id": "p_riya",
                "affected_location_id": None,
            },
            "scenario": {"seed": seed, "fault": S7_FAULT},
            "max_parallel_calls": 1,
            "presence_checks": True,
        }
    raise ValueError("scenario must be S1, S2, or S7")


def _event_writer(output: TextIO, started: float) -> tuple[Any, Any]:
    def emit(message: str) -> None:
        elapsed = time.monotonic() - started
        print(f"[{elapsed:6.1f}s] {message}", file=output, flush=True)

    def event(data: dict[str, Any]) -> None:
        kind = data["type"]
        if kind == "question":
            question = data["question"]
            action = question["action"]
            emit(
                f"ask {action['participant_id']} ({question['language']}): {question['text']} "
                f"| in flight: {data['pending_count']}"
            )
        elif kind == "answer":
            detail = data["detail"]
            if detail["claim"]:
                emit(
                    f"claim from guard desk: standing in IDF-2; switch lights are green; "
                    f"answer {detail['phrase']!r} -> {detail['outcome']}"
                )
            elif detail["probe_id"] is None:
                emit(f"label check at {detail['card_label']}: {detail['outcome']}")
            else:
                lie = " (misreported)" if detail["misreported"] else ""
                emit(
                    f"card {detail['card_label']}: {detail['observed']}; "
                    f"answer {detail['phrase']!r} -> {detail['outcome']}{lie}"
                )
        elif kind == "approval":
            emit(f"approved by {data['approver_id']}: {data['label']} {data['target']}")
        elif kind == "repair":
            emit("repair performed; held-out verification started")

    return emit, event


def _is_approver_only_session(principal: Any) -> bool:
    if not isinstance(principal, dict) or principal.get("method") != "session":
        return False
    roles = principal.get("roles")
    return isinstance(roles, list) and "approver" in roles and "operator" not in roles


def _require_approver_session(client: httpx.Client) -> None:
    try:
        response = client.get("/v1/auth/session", follow_redirects=False)
    except httpx.HTTPError as exc:
        raise RehearsalError(f"approver session check failed ({type(exc).__name__})") from exc
    if response.status_code != 200:
        raise RehearsalError(
            "S1 requires an authenticated approver-only session; "
            f"session check returned HTTP {response.status_code}"
        )
    try:
        principal = response.json()
    except ValueError as exc:
        raise RehearsalError("S1 requires an authenticated approver-only session") from exc
    if not _is_approver_only_session(principal):
        raise RehearsalError("S1 requires an authenticated approver-only session")


def run_rehearsal(
    core: httpx.Client,
    sim: httpx.Client,
    *,
    scenario: str,
    output: TextIO | None = None,
    seed: int = 19,
    approver: httpx.Client | None = None,
    variant: str = "adversary",
) -> dict[str, Any]:
    name = scenario.upper()
    if name not in {"S1", "S2", "S7"}:
        raise ValueError("scenario must be S1, S2, or S7")
    if variant not in {"adversary", "honest"}:
        raise ValueError("variant must be adversary or honest")
    if name == "S1":
        if approver is None:
            raise RehearsalError(
                "S1 requires an authenticated approver-only session; set "
                "PRAMANA_APPROVER_EMAIL and PRAMANA_APPROVER_PASSWORD"
            )
        _require_approver_session(approver)

    stream = output or sys.stdout
    started = time.monotonic()
    emit, on_event = _event_writer(stream, started)
    request = scenario_request(name, seed=seed)
    if name == "S1":
        state = create_investigation(
            core,
            seed=seed,
            fault="CB_C2_7.tripped",
            max_parallel_calls=3,
            participants=request["participants"],
            report_text=request["report"]["text"],
            reporter_id=request["report"]["reporter_id"],
            presence_checks=request["presence_checks"],
        )
    else:
        state = create_request(core, request)
    parallelism = int(request["max_parallel_calls"])
    emit(
        f"{name} investigation {state['id']} created; People asked at once: {parallelism}; "
        f"sealed commitment {state['sealed_commitment']}"
    )

    play_variant = variant if name == "S7" else "honest"
    state, steps, observed_parallelism = play_pending(
        core,
        sim,
        state,
        variant=play_variant,
        on_event=on_event,
    )
    emit(f"conclusion: {state['status']} ({state['plan']['reason']})")

    verification_status: str | None = None
    if name == "S1":
        if state["status"] != "decided":
            raise RehearsalError(f"S1 did not reach a repair decision: {state['status']}")
        state, repair_steps, repair_parallel = repair_and_verify(
            core,
            sim,
            state,
            approver=approver,
            on_event=on_event,
        )
        steps += repair_steps
        observed_parallelism = max(observed_parallelism, repair_parallel)
        verification_status = state["status"]
        if verification_status != "verified":
            raise RehearsalError(f"S1 repair verification ended as {verification_status}")
        emit(f"verification result: {verification_status}")

    if name == "S2" and not state.get("disagreements"):
        raise RehearsalError("S2 did not produce a disagreement explanation")
    if name == "S7":
        expected = "failed" if variant == "adversary" else "passed"
        checks = [item["status"] for item in state.get("presence_checks", [])]
        if expected not in checks:
            raise RehearsalError(f"S7 {variant} run did not produce a {expected} label check")
        emit(f"S7 {variant}: IDF-2 presence label check {expected}")

    revealed, replay = reveal_and_replay(core, state["id"])
    ground_truth = revealed.get("ground_truth", {})
    reveal = ground_truth.get("reveal", {})
    commitment_matches = reveal.get("commitment") == state["sealed_commitment"]
    commitment_verified = reveal.get("commitment_verified") is True
    replay_identical = replay.get("identical") is True
    if not commitment_matches or not commitment_verified:
        raise RehearsalError("revealed fault did not match the published commitment")
    if not replay_identical:
        raise RehearsalError("event replay did not reproduce the recorded state")
    if name in {"S1", "S2"} and ground_truth.get("correct") is not True:
        raise RehearsalError(f"{name} diagnosis did not match the revealed fault")

    emit(
        f"reveal: {reveal_summary(revealed)}; commitment verified: {commitment_verified}; "
        f"correct: {ground_truth.get('correct')}"
    )
    emit(f"replay identical: {replay_identical}; events {replay.get('events_replayed', 'unknown')}")
    return {
        "scenario": name,
        "variant": variant if name == "S7" else None,
        "skipped": False,
        "investigation_id": state["id"],
        "sealed_commitment": state["sealed_commitment"],
        "parallelism": parallelism,
        "max_parallel_observed": observed_parallelism,
        "questions_asked": revealed.get("questions_asked", steps),
        "verification_status": verification_status,
        "presence_checks": revealed.get("presence_checks", []),
        "reveal": revealed,
        "replay": replay,
    }


def _env_values() -> dict[str, str]:
    from pramana_core.llm import read_env_file

    values = read_env_file(ROOT / ".env")
    values.update(os.environ)
    return values


def _approver_client(base_url: str, env: dict[str, str]) -> httpx.Client:
    email = env.get("PRAMANA_APPROVER_EMAIL", "").strip()
    password = env.get("PRAMANA_APPROVER_PASSWORD", "")
    if not email and not password:
        raise RehearsalError(
            "S1 requires a separate authenticated approver; set "
            "PRAMANA_APPROVER_EMAIL and PRAMANA_APPROVER_PASSWORD"
        )
    if not email or not password:
        raise RehearsalError(
            "set both PRAMANA_APPROVER_EMAIL and PRAMANA_APPROVER_PASSWORD "
            "for an approver-only session"
        )
    client = httpx.Client(base_url=base_url, timeout=60.0, follow_redirects=False)
    try:
        response = client.post(
            "/v1/auth/login",
            headers={"X-Pramana-CSRF": "1"},
            json={"email": email, "password": password},
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        client.close()
        raise RehearsalError(f"approver sign-in failed ({type(exc).__name__})") from exc
    if response.status_code != 200:
        client.close()
        raise RehearsalError(f"approver sign-in failed with HTTP {response.status_code}")
    try:
        principal = response.json()
    except ValueError as exc:
        client.close()
        raise RehearsalError("approver sign-in returned an invalid session") from exc
    if not _is_approver_only_session(principal):
        client.close()
        raise RehearsalError("approver credentials must belong to an approver-only account")
    try:
        _require_approver_session(client)
    except RehearsalError:
        client.close()
        raise
    return client


def _write_report(path: Path, result: dict[str, Any]) -> None:
    revealed = result.get("reveal", {})
    ground_truth = revealed.get("ground_truth", {})
    reveal = ground_truth.get("reveal", {})
    report = {
        "scenario": result["scenario"],
        "variant": result.get("variant"),
        "investigation_id": result.get("investigation_id"),
        "questions_asked": result.get("questions_asked"),
        "parallelism": result.get("parallelism"),
        "max_parallel_observed": result.get("max_parallel_observed"),
        "verification_status": result.get("verification_status"),
        "presence_checks": result.get("presence_checks", []),
        "commitment_verified": reveal.get("commitment_verified"),
        "commitment_matches": reveal.get("commitment") == result.get("sealed_commitment"),
        "correct": ground_truth.get("correct"),
        "replay_identical": result.get("replay", {}).get("identical"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Rehearse a Pramana demo scenario in text mode")
    parser.add_argument("--scenario", choices=("S1", "S2", "S7"), required=True)
    parser.add_argument("--core", default="http://127.0.0.1:8000")
    parser.add_argument("--sim", default="http://127.0.0.1:8100")
    parser.add_argument("--seed", type=int, default=19)
    parser.add_argument("--variant", choices=("adversary", "honest"), default="adversary")
    parser.add_argument("--report", type=Path, help="write a generated JSON rehearsal summary")
    args = parser.parse_args(argv)
    env = _env_values()
    headers = automation_headers()
    try:
        with (
            httpx.Client(
                base_url=args.core,
                timeout=60.0,
                headers=headers,
                follow_redirects=False,
            ) as core,
            httpx.Client(base_url=args.sim, timeout=30.0, follow_redirects=False) as sim,
        ):
            approver: httpx.Client | None = None
            try:
                if args.scenario == "S1":
                    approver = _approver_client(args.core, env)
                result = run_rehearsal(
                    core,
                    sim,
                    scenario=args.scenario,
                    seed=args.seed,
                    approver=approver,
                    variant=args.variant,
                )
                if args.report:
                    _write_report(args.report, result)
            finally:
                if approver is not None:
                    approver.close()
    except (httpx.HTTPError, RehearsalError, ValueError) as exc:
        print(f"FAIL rehearsal: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
