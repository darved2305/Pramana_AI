"""A simulated participant for end-to-end tests.

It sees the world only through the simulator, with its own participant token (exactly what a
human participant's browser gets), and answers in natural text that the core must extract.

The functions take any ``httpx.Client``: a FastAPI ``TestClient`` for in-process tests, or a
plain client pointed at running services (``tests/e2e``).
"""

from __future__ import annotations

from typing import Any

import httpx

# How a participant might say each outcome (Hinglish / Marathi / English mix on purpose).
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


def answer_pending(
    core: httpx.Client,
    sim: httpx.Client,
    inv: dict[str, Any],
    override: dict[str, str] | None = None,
) -> dict[str, Any]:
    q = inv["pending_question"]
    a = q["action"]
    tok = core.post(f"/v1/investigations/{inv['id']}/participants/{a['participant_id']}/token")
    assert tok.status_code == 200, tok.text
    sid, headers = tok.json()["scenario_id"], {"Authorization": f"Bearer {tok.json()['token']}"}
    if a["requires_move"]:
        moved = sim.post(
            f"/sim/v1/scenarios/{sid}/move", json={"to": a["location_id"]}, headers=headers
        )
        assert moved.status_code == 200, moved.text
    seen = sim.post(
        f"/sim/v1/scenarios/{sid}/observe", json={"probe_id": a["probe_id"]}, headers=headers
    )
    assert seen.status_code == 200, seen.text
    value = seen.json()["value"]
    if override and a["probe_id"] in override:
        value = override[a["probe_id"]]
    r = core.post(
        f"/v1/investigations/{inv['id']}/answers",
        json={
            "question_id": q["id"],
            "participant_id": a["participant_id"],
            "text": PHRASES.get(value, value.replace("_", " ")),
        },
    )
    assert r.status_code == 200, r.text
    result: dict[str, Any] = r.json()
    assert result["extraction"]["outcome"] == value, (
        PHRASES.get(value, value),
        result["extraction"],
    )
    return result


def run_to_conclusion(
    core: httpx.Client, sim: httpx.Client, inv: dict[str, Any], max_steps: int = 15, **kw: Any
) -> tuple[dict[str, Any], list[str]]:
    path: list[str] = []
    for _ in range(max_steps):
        if inv["pending_question"] is None:
            return inv, path
        a = inv["pending_question"]["action"]
        path.append(f"{a['participant_id']}:{a['probe_id']}@{a['location_id']}")
        inv = answer_pending(core, sim, inv, **kw)["state"]
    raise AssertionError(f"no conclusion after {max_steps} questions: {path}")
