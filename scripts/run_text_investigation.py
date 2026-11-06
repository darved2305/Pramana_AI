"""Run one text-mode investigation against the live core and simulator services."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import httpx

try:
    from .core_auth import automation_headers
    from .text_investigation import (
        PEOPLE,
        RehearsalError,
        create_investigation,
        play_pending,
        repair_and_verify,
        response_json,
    )
except ImportError:
    from core_auth import automation_headers
    from text_investigation import (
        PEOPLE,
        RehearsalError,
        create_investigation,
        play_pending,
        repair_and_verify,
        response_json,
    )


def _print_event(data: dict[str, Any]) -> None:
    if data["type"] == "question":
        question = data["question"]
        action = question["action"]
        state = data["state"]
        best = next(
            (
                candidate
                for candidate in state["plan"]["candidates"]
                if candidate["action"] == state["plan"]["action"]
            ),
            None,
        )
        print(f"\n[{data['step']}] ask {action['participant_id']} ({question['language']}):")
        print(f"    {question['text']}")
        if best is not None:
            print(
                f"    why: EIG_D {best['eig_decision_bits']:.2f} bits, "
                f"cost {best['cost_s']:.0f} s, net value {best['net_value_min']:.2f} min"
            )
            print(
                "    previews: "
                + ", ".join(
                    f"{outcome['outcome']}->{outcome['decision']}"
                    f"({outcome['decision_probability']:.2f})"
                    for outcome in best["outcomes"]
                )
            )
    elif data["type"] == "answer":
        detail = data["detail"]
        state = data["state"]
        note = " (MISREPORTED)" if detail["misreported"] else ""
        print(f"    card: {detail['card_label']}: {detail['observed']}")
        print(f"    answer: {detail['phrase']!r} -> {detail['outcome']}{note}")
        belief = state["belief"]
        print(f"    belief: {belief['map_decision']} P={belief['map_decision_probability']:.3f}")
        print(
            f"    top cause {belief['hypotheses'][0]['id']} "
            f"{belief['hypotheses'][0]['probability']:.3f}; "
            f"P(unknown cause)={belief['open_world_probability']:.3f}"
        )
        if detail["voice"].get("stt"):
            print(f"    Prisma transcript: {detail['voice']['stt']!r}")
    elif data["type"] == "approval":
        print(f"\napproved by {data['approver_id']}: {data['label']} {data['target']}")
    elif data["type"] == "repair":
        print("repair reported; held-out verification started")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run one text-mode investigation")
    parser.add_argument("--core", default="http://127.0.0.1:8000")
    parser.add_argument("--sim", default="http://127.0.0.1:8100")
    parser.add_argument("--seed", type=int, default=19)
    parser.add_argument("--fault", help="component.mode, default: random (sealed)")
    parser.add_argument("--lie", action="append", default=[], help="probe_id=outcome to misreport")
    parser.add_argument("--voice", action="store_true", help="speak every turn through real Gnani")
    parser.add_argument(
        "--repair", action="store_true", help="approve a breaker reset and verify the repair"
    )
    parser.add_argument(
        "--exclude", action="append", default=[], help="participant id to leave out"
    )
    args = parser.parse_args(argv)

    try:
        lies = dict(item.split("=", 1) for item in args.lie)
        participants = [person for person in PEOPLE if person["id"] not in args.exclude]
        with (
            httpx.Client(
                base_url=args.core,
                timeout=60.0,
                headers=automation_headers(),
                follow_redirects=False,
            ) as core,
            httpx.Client(base_url=args.sim, timeout=30.0, follow_redirects=False) as sim,
        ):
            state = create_investigation(
                core,
                seed=args.seed,
                fault=args.fault or "random",
                participants=participants,
            )
            print(f"investigation {state['id']}  sealed commitment {state['sealed_commitment']}")
            state, _steps, _parallelism = play_pending(
                core,
                sim,
                state,
                voice=args.voice,
                lies=lies,
                on_event=_print_event,
            )
            print(f"\nconclusion: {state['status']}: {state['plan']['reason']}")
            if args.repair and state["status"] == "decided":
                state, _repair_steps, _repair_parallelism = repair_and_verify(
                    core,
                    sim,
                    state,
                    on_event=_print_event,
                    voice=args.voice,
                    lies=lies,
                )
                print(f"\nverification result: {state['status']}: {state['plan']['reason']}")
            revealed = response_json(core.post(f"/v1/investigations/{state['id']}/reveal"))
            ground_truth = revealed.get("ground_truth", {})
            reveal = ground_truth.get("reveal", {})
            print("revealed fault:", json.dumps(reveal.get("fault_spec", {}).get("faults", [])))
            print(
                f"commitment verified: {reveal.get('commitment_verified')}; "
                f"matches published: {reveal.get('commitment') == state['sealed_commitment']}"
            )
            print(
                f"true decision: {ground_truth.get('true_decision_classes')}  "
                f"concluded: {ground_truth.get('concluded_decision')}  "
                f"correct: {ground_truth.get('correct')}"
            )
    except (httpx.HTTPError, RehearsalError, ValueError) as exc:
        print(f"FAIL investigation: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
