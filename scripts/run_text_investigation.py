"""Run one complete text-mode investigation against live core and simulator services.

Each simulated participant sees the world only through the simulator with its own token and
answers in natural code-mixed text. At the end the sealed fault is revealed and checked against
the commitment published at the start.

With ``--voice`` every turn is spoken end to end through real Gnani: the question is
synthesised by Timbre in the participant's language, the answer phrase is synthesised too
(standing in for a person speaking), then transcribed by Prisma v3.0 with the question's
context, extracted, and applied. This spends credits (roughly Rs 0.3 per turn).

Usage: python scripts/run_text_investigation.py [--seed N] [--fault CB_C2_7.tripped]
       [--lie probe_id=outcome] [--voice] [--core http://127.0.0.1:8000]
       [--sim http://127.0.0.1:8100]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

from pramana_core.llm import read_env_file

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

# What a Marathi or Hindi speaker might say, in their own script (used with --voice).
NATIVE = {
    "mr": {
        "yes": "हो, उघडतं",
        "no": "नाही, उघडत नाही",
        "on": "हो, चालू आहे",
        "off": "बंद आहे",
        "green": "हिरवे दिवे आहेत",
        "amber": "नारंगी दिवे आहेत",
        "red": "लाल आहे",
        "up": "ब्रेकर वर आहे",
        "tripped": "ब्रेकर खाली आहे, ट्रिप झालाय",
        "no_network": "NAVA-WiFi दिसतच नाही",
        "stuck_connecting": "कनेक्ट होताना अडकलंय",
        "connected": "कनेक्टेड आहे",
    },
    "hi": {
        "yes": "हाँ, खुल रही है",
        "no": "नहीं, खुल नहीं रही",
        "on": "हाँ, चालू है",
        "off": "बंद है",
        "green": "हरी लाइट है",
        "amber": "नारंगी है",
        "red": "लाल है",
        "up": "ब्रेकर ऊपर है",
        "tripped": "ब्रेकर नीचे है, ट्रिप है",
        "no_network": "NAVA-WiFi दिख ही नहीं रहा",
        "stuck_connecting": "कनेक्ट होने पर अटका है",
        "connected": "कनेक्टेड है",
    },
}
TTS_LANG = {"mr": "mr-IN", "hi": "hi-IN", "hi-en": "hi-en", "en": "en-IN"}

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

ROOT = Path(__file__).resolve().parents[1]


def check(r: httpx.Response) -> Any:
    if r.status_code >= 400:
        sys.exit(f"HTTP {r.status_code} {r.request.method} {r.request.url}: {r.text[:300]}")
    return r.json()


def repair_and_verify(
    core: httpx.Client, sim: httpx.Client, inv: dict[str, Any], play: Any, step: int
) -> tuple[dict[str, Any], int]:
    """Human approval -> single-use capability -> act in the simulator -> verification."""
    top = inv["belief"]["hypotheses"][0]["id"]
    target, _, mode = top.partition(".")
    if mode != "tripped":
        print(f"no approval-gated action for {top}; stopping at the decision")
        return inv, step
    url = f"/v1/investigations/{inv['id']}/approvals"
    state = check(
        core.post(
            url, json={"action": "reset_breaker", "target": target, "participant_id": "p_imran"}
        )
    )
    approval = state["approvals"][-1]
    print(
        f"\napproval requested: {approval['action_label']} {target} "
        f"(risk {approval['risk']}, reversible {approval['reversible']})"
    )
    check(
        core.post(
            f"{url}/{approval['id']}/decision",
            json={"decision": "approve", "approver_id": "u_duty_manager"},
        )
    )
    grant = check(
        core.post(f"{url}/{approval['id']}/capability", params={"participant_id": "p_imran"})
    )
    print(f"approved; capability issued to p_imran until {grant['expires_at']}")
    print(f"   instruction: {grant['instructions']}")
    tok = check(core.post(f"/v1/investigations/{inv['id']}/participants/p_imran/token"))
    h = {"Authorization": f"Bearer {tok['token']}"}
    sid = tok["scenario_id"]
    panel = "DB_C2_PANEL" if target.startswith("CB_C2") else "IDF1"
    check(sim.post(f"/sim/v1/scenarios/{sid}/move", json={"to": panel}, headers=h))
    done = check(
        sim.post(
            f"/sim/v1/scenarios/{sid}/act",
            headers=h,
            json={"action": "reset_breaker", "target": target, "capability": grant["capability"]},
        )
    )
    print(f"simulator: {done}")
    inv = check(
        core.post(
            f"/v1/investigations/{inv['id']}/interventions",
            json={"approval_id": approval["id"], "participant_id": "p_imran"},
        )
    )
    print(
        f"verification: P(fixed) = {inv['belief']['repair']['fixed_probability']:.3f} "
        "before any new observation"
    )
    inv, step = play(inv, step)
    print(f"\nverification result: {inv['status']}: {inv['plan']['reason']}")
    return inv, step


def check_audio(r: httpx.Response, what: str) -> None:
    if r.status_code != 200 or r.content[:4] != b"RIFF":
        sys.exit(f"{what}: HTTP {r.status_code} {r.text[:300]}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Devanagari on Windows consoles
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", default="http://127.0.0.1:8000")
    ap.add_argument("--sim", default="http://127.0.0.1:8100")
    ap.add_argument("--seed", type=int, default=19)
    ap.add_argument("--fault", default=None, help="component.mode, default: random (sealed)")
    ap.add_argument("--lie", action="append", default=[], help="probe_id=outcome to misreport")
    ap.add_argument("--voice", action="store_true", help="speak every turn through real Gnani")
    ap.add_argument(
        "--repair",
        action="store_true",
        help="after a decision: approve, reset in the simulator, then verify",
    )
    ap.add_argument("--exclude", action="append", default=[], help="participant id to leave out")
    args = ap.parse_args()
    lies = dict(item.split("=", 1) for item in args.lie)
    fault: Any = "random"
    if args.fault:
        comp, mode = args.fault.split(".")
        fault = {"faults": [{"component_id": comp, "mode": mode}]}

    # The core enforces sign-in outside tests; scripts act through the automation key.
    key = os.environ.get("CORE_AUTOMATION_KEY") or read_env_file(ROOT / ".env").get(
        "CORE_AUTOMATION_KEY", ""
    )
    auth = {"X-Automation-Key": key} if key else {}
    core = httpx.Client(base_url=args.core, timeout=60, headers=auth)
    sim = httpx.Client(base_url=args.sim)
    inv = check(
        core.post(
            "/v1/investigations",
            json={
                "pack_id": "campus_block_c",
                "participants": [p for p in PEOPLE if p["id"] not in args.exclude],
                "report": {
                    "text": "Floor 3 pe WiFi nahi chal raha, kuch khul nahi raha",
                    "reporter_id": "p_riya",
                },
                "scenario": {"seed": args.seed, "fault": fault},
            },
        )
    )
    print(f"investigation {inv['id']}  sealed commitment {inv['sealed_commitment']}")

    def play(inv: dict[str, Any], step: int) -> tuple[dict[str, Any], int]:
        while inv["pending_question"] is not None:
            step += 1
            q, a = inv["pending_question"], inv["pending_question"]["action"]
            best = next(
                c for c in inv["plan"]["candidates"] if c["action"] == inv["plan"]["action"]
            )
            tok = check(
                core.post(
                    f"/v1/investigations/{inv['id']}/participants/{a['participant_id']}/token"
                )
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
            lang = q["language"]
            phrase = NATIVE.get(lang, PHRASES)[said] if args.voice else PHRASES[said]
            if args.voice:
                spoken_q = core.get(f"/v1/investigations/{inv['id']}/questions/{q['id']}/audio")
                check_audio(spoken_q, "question audio")
                answer_wav = core.post(
                    "/v1/voice/tts", json={"text": phrase, "language": TTS_LANG[lang]}
                )
                check_audio(answer_wav, "answer audio")
                r = core.post(
                    f"/v1/investigations/{inv['id']}/answers/voice",
                    data={"question_id": q["id"], "participant_id": a["participant_id"]},
                    files={"audio": ("answer.wav", answer_wav.content, "audio/wav")},
                )
                voiced = check(r)
                res = voiced["result"]
                stt = voiced["stt"]
                print(
                    f"    spoke question ({len(spoken_q.content)} B WAV); "
                    f"participant said {phrase!r}; Prisma heard {stt['transcript']!r} "
                    f"[{stt['detected_language']}]"
                )
            else:
                res = check(
                    core.post(
                        f"/v1/investigations/{inv['id']}/answers",
                        json={
                            "question_id": q["id"],
                            "participant_id": a["participant_id"],
                            "text": phrase,
                        },
                    )
                )
            inv = res["state"]
            b = inv["belief"]
            lie = "  (MISREPORTED)" if said != seen else ""
            heard_ok = "" if res["extraction"]["outcome"] == said else "  (NOT UNDERSTOOD AS SAID)"
            print(f"    answer: {phrase!r} -> {res['extraction']['outcome']}{lie}{heard_ok}")
            print(
                f"    belief: {b['map_decision']} P={b['map_decision_probability']:.3f}, "
                f"top cause {b['hypotheses'][0]['id']} {b['hypotheses'][0]['probability']:.3f}, "
                f"P(unknown cause)={b['open_world_probability']:.3f}"
            )
        return inv, step

    inv, step = play(inv, 0)
    print(f"\nconclusion: {inv['status']}: {inv['plan']['reason']}")
    if args.repair and inv["status"] == "decided":
        inv, step = repair_and_verify(core, sim, inv, play, step)
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
