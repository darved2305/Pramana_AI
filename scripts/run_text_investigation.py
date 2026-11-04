"""Run one complete text-mode investigation against live core and simulator services.

Each simulated participant sees the world only through the simulator with its own token and
answers in natural code-mixed text. At the end the sealed fault is revealed and checked against
the commitment published at the start.

Usage: python scripts/run_text_investigation.py [--seed N] [--fault CB_C2_7.tripped]
       [--lie probe_id=outcome] [--core http://127.0.0.1:8000] [--sim http://127.0.0.1:8100]
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import httpx

PHRASES = {
    "yes": "haan, khul rahi hai",
    "no": "nahi, khul nahi rahi",
    "on": "haan chalu hai",
    "off": "band aahe",
    "green": "lights green hain",
    "amber": "orange dikh rahi hain",
    "red": "laal hai",
    "up": "breaker upar hai",
    "tripped": "breaker neeche hai, trip hai",
    "no_network": "NAVA-WiFi dikh hi nahi raha",
    "stuck_connecting": "connecting pe atka hai",
    "connected": "connected hai",
}

PEOPLE = [
    {
        "id": "p_riya",
        "display_name": "Riya",
        "roles": ["student"],
        "skill": "lay",
        "location_id": "F3_R304",
        "languages": {
            "stt_candidates": ["hi-IN", "en-IN"],
            "template_language": "hi-en",
            "codemix": True,
        },
    },
    {
        "id": "p_mahesh",
        "display_name": "Mahesh",
        "roles": ["guard"],
        "skill": "access",
        "location_id": "GUARD_DESK",
        "languages": {"stt_candidates": ["mr-IN", "hi-IN"], "template_language": "mr"},
    },
    {
        "id": "p_imran",
        "display_name": "Imran",
        "roles": ["electrician"],
        "skill": "technician",
        "location_id": "MAINT_ROOM",
        "languages": {"stt_candidates": ["hi-IN"], "template_language": "hi"},
    },
]


def check(r: httpx.Response) -> Any:
    if r.status_code >= 400:
        sys.exit(f"HTTP {r.status_code} {r.request.method} {r.request.url}: {r.text[:300]}")
    return r.json()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Devanagari on Windows consoles
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", default="http://127.0.0.1:8000")
    ap.add_argument("--sim", default="http://127.0.0.1:8100")
    ap.add_argument("--seed", type=int, default=19)
    ap.add_argument("--fault", default=None, help="component.mode, default: random (sealed)")
    ap.add_argument("--lie", action="append", default=[], help="probe_id=outcome to misreport")
    args = ap.parse_args()
    lies = dict(item.split("=", 1) for item in args.lie)
    fault: Any = "random"
    if args.fault:
        comp, mode = args.fault.split(".")
        fault = {"faults": [{"component_id": comp, "mode": mode}]}

    core, sim = httpx.Client(base_url=args.core, timeout=20), httpx.Client(base_url=args.sim)
    inv = check(
        core.post(
            "/v1/investigations",
            json={
                "pack_id": "campus_block_c",
                "participants": PEOPLE,
                "report": {
                    "text": "Floor 3 pe WiFi nahi chal raha, kuch khul nahi raha",
                    "reporter_id": "p_riya",
                },
                "scenario": {"seed": args.seed, "fault": fault},
            },
        )
    )
    print(f"investigation {inv['id']}  sealed commitment {inv['sealed_commitment']}")
    step = 0
    while inv["pending_question"] is not None:
        step += 1
        q, a = inv["pending_question"], inv["pending_question"]["action"]
        best = next(c for c in inv["plan"]["candidates"] if c["action"] == inv["plan"]["action"])
        tok = check(
            core.post(f"/v1/investigations/{inv['id']}/participants/{a['participant_id']}/token")
        )
        h = {"Authorization": f"Bearer {tok['token']}"}
        if a["requires_move"]:
            check(
                sim.post(
                    f"/sim/v1/scenarios/{tok['scenario_id']}/move",
                    json={"to": a["location_id"]},
                    headers=h,
                )
            )
        seen = check(
            sim.post(
                f"/sim/v1/scenarios/{tok['scenario_id']}/observe",
                json={"probe_id": a["probe_id"]},
                headers=h,
            )
        )["value"]
        said = lies.get(a["probe_id"], seen)
        print(f"\n[{step}] ask {a['participant_id']} ({q['language']}): {q['text']}")
        print(
            f"    why: EIG_D {best['eig_decision_bits']:.2f} bits, cost {best['cost_s']:.0f} s,"
            f" net value {best['net_value_min']:.2f} min"
        )
        print(
            "    previews: "
            + ", ".join(
                f"{o['outcome']}->{o['decision']}({o['decision_probability']:.2f})"
                for o in best["outcomes"]
            )
        )
        res = check(
            core.post(
                f"/v1/investigations/{inv['id']}/answers",
                json={
                    "question_id": q["id"],
                    "participant_id": a["participant_id"],
                    "text": PHRASES[said],
                },
            )
        )
        inv = res["state"]
        b = inv["belief"]
        lie = "  (MISREPORTED)" if said != seen else ""
        print(f"    answer: {PHRASES[said]!r} -> {res['extraction']['outcome']}{lie}")
        print(
            f"    belief: {b['map_decision']} P={b['map_decision_probability']:.3f}, "
            f"top cause {b['hypotheses'][0]['id']} {b['hypotheses'][0]['probability']:.3f}, "
            f"P(unknown cause)={b['open_world_probability']:.3f}"
        )
    print(f"\nconclusion: {inv['status']}: {inv['plan']['reason']}")
    final = check(core.post(f"/v1/investigations/{inv['id']}/reveal"))
    gt = final["ground_truth"]
    print("revealed fault:", json.dumps(gt["reveal"]["fault_spec"]["faults"]))
    print(
        f"commitment verified: {gt['reveal']['commitment_verified']}; "
        f"matches published: {gt['reveal']['commitment'] == inv['sealed_commitment']}"
    )
    print(
        f"true decision: {gt['true_decision_classes']}  concluded: {gt['concluded_decision']}"
        f"  correct: {gt['correct']}"
    )


if __name__ == "__main__":
    main()
