"""Shared text participant and repair helpers for investigation scripts."""

from __future__ import annotations

import json
from collections.abc import Callable
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
ADVERSARY_LIE = {
    "off": "green",
    "green": "off",
    "amber": "green",
    "on": "off",
    "tripped": "up",
    "up": "tripped",
}

PEOPLE: list[dict[str, Any]] = [
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


class RehearsalError(RuntimeError):
    """A service failed or the rehearsal did not meet its expected outcome."""


def response_json(response: httpx.Response) -> Any:
    if response.status_code >= 400:
        raise RehearsalError(
            f"HTTP {response.status_code} {response.request.method} "
            f"{response.request.url}: {response.text[:300]}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise RehearsalError("service returned invalid JSON") from exc


def create_request(core: httpx.Client, body: dict[str, Any]) -> dict[str, Any]:
    return response_json(core.post("/v1/investigations", json=body))


def create_investigation(
    core: httpx.Client,
    *,
    seed: int,
    fault: str | dict[str, Any] = "random",
    max_parallel_calls: int = 1,
    participants: list[dict[str, Any]] | None = None,
    report_text: str = "Floor 3 pe WiFi nahi chal raha, kuch khul nahi raha",
    reporter_id: str = "p_riya",
    presence_checks: bool = False,
) -> dict[str, Any]:
    fault_spec: str | dict[str, Any] = fault
    if isinstance(fault, str) and fault != "random":
        component, separator, mode = fault.partition(".")
        if not separator or not component or not mode:
            raise ValueError("fault must be component.mode or random")
        fault_spec = {"faults": [{"component_id": component, "mode": mode}]}
    body = {
        "pack_id": "campus_block_c",
        "participants": PEOPLE if participants is None else participants,
        "report": {"text": report_text, "reporter_id": reporter_id, "affected_location_id": None},
        "scenario": {"seed": seed, "fault": fault_spec},
        "max_parallel_calls": max_parallel_calls,
        "presence_checks": presence_checks,
    }
    return create_request(core, body)


def pending_questions(state: dict[str, Any]) -> list[dict[str, Any]]:
    waiting = state.get("pending_questions")
    if waiting:
        return list(waiting)
    question = state.get("pending_question")
    return [question] if question else []


def _token(core: httpx.Client, inv_id: str, participant_id: str) -> dict[str, Any]:
    return response_json(
        core.post(f"/v1/investigations/{inv_id}/participants/{participant_id}/token")
    )


def _view(
    sim: httpx.Client,
    token: dict[str, Any],
    action: dict[str, Any],
    *,
    move: bool,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token['token']}"}
    scenario_id = token["scenario_id"]
    if move and action.get("requires_move"):
        response_json(
            sim.post(
                f"/sim/v1/scenarios/{scenario_id}/move",
                json={"to": action["location_id"]},
                headers=headers,
            )
        )
    return response_json(sim.get(f"/sim/v1/scenarios/{scenario_id}/view", headers=headers))


def _card_value(
    sim: httpx.Client,
    token: dict[str, Any],
    action: dict[str, Any],
) -> tuple[str, str]:
    view = _view(sim, token, action, move=True)
    item = next(
        (item for item in view.get("items", []) if item.get("probe_id") == action["probe_id"]),
        None,
    )
    if item is None:
        raise RehearsalError(
            f"{action['participant_id']}'s simulator card has no {action['probe_id']} item"
        )
    return str(item["value"]), str(item["label"])


def _challenge_reading(
    sim: httpx.Client,
    token: dict[str, Any],
    action: dict[str, Any],
    *,
    move: bool,
) -> tuple[str, str]:
    view = _view(sim, token, action, move=move)
    labels = view.get("labels", [])
    if not labels:
        return "I can't see any label from here, sorry", str(
            view.get("location_label", "current place")
        )
    label = labels[0]
    value = str(label["value"])
    return f"it says {' '.join(value)}", str(label.get("label", "label"))


def _check_audio(response: httpx.Response, what: str) -> bytes:
    if response.status_code != 200 or not response.content.startswith(b"RIFF"):
        raise RehearsalError(f"{what} failed with HTTP {response.status_code}")
    return response.content


def answer_question(
    core: httpx.Client,
    sim: httpx.Client,
    state: dict[str, Any],
    question: dict[str, Any],
    *,
    lies: dict[str, str] | None = None,
    voice: bool = False,
    variant: str = "honest",
) -> tuple[dict[str, Any], dict[str, Any]]:
    action = question["action"]
    participant_id = action["participant_id"]
    token = _token(core, state["id"], participant_id)
    language = question["language"]
    claim = False

    if question.get("kind") == "challenge":
        phrase, card_label = _challenge_reading(
            sim,
            token,
            action,
            move=variant != "adversary",
        )
        said = phrase
        observed = phrase
    elif variant == "adversary" and action.get("location_id") == "IDF2":
        # Simulate the dishonest guard checking the card, returning to the desk, then lying.
        headers = {"Authorization": f"Bearer {token['token']}"}
        scenario_id = token["scenario_id"]
        home = next(
            (person["location_id"] for person in PEOPLE if person["id"] == participant_id),
            "GUARD_DESK",
        )
        response_json(
            sim.post(
                f"/sim/v1/scenarios/{scenario_id}/move",
                json={"to": "IDF2"},
                headers=headers,
            )
        )
        try:
            view = _view(sim, token, action, move=False)
            item = next(
                (
                    item
                    for item in view.get("items", [])
                    if item.get("probe_id") == action.get("probe_id")
                ),
                None,
            )
            if item is None:
                raise RehearsalError(
                    f"{participant_id}'s simulator card has no {action.get('probe_id')} item"
                )
            observed = str(item["value"])
            card_label = str(item["label"])
        finally:
            response_json(
                sim.post(
                    f"/sim/v1/scenarios/{scenario_id}/move",
                    json={"to": home},
                    headers=headers,
                )
            )
        said = ADVERSARY_LIE.get(observed, observed)
        phrase = PHRASES[said]
        if action.get("probe_id") != "switch_leds":
            phrase += "; IDF-2 switch lights are green"
        claim = True
    else:
        observed, card_label = _card_value(sim, token, action)
        said = (lies or {}).get(action["probe_id"], observed)
        phrase = NATIVE.get(language, PHRASES)[said] if voice else PHRASES[said]

    if question.get("kind") == "challenge":
        response = core.post(
            f"/v1/investigations/{state['id']}/answers",
            json={
                "question_id": question["id"],
                "participant_id": participant_id,
                "text": phrase,
            },
        )
        result = response_json(response)
        state = result["state"]
        outcome = result["extraction"]["outcome"]
        voice_detail: dict[str, Any] = {}
    elif voice:
        _check_audio(
            core.get(f"/v1/investigations/{state['id']}/questions/{question['id']}/audio"),
            "question audio",
        )
        answer_audio = _check_audio(
            core.post("/v1/voice/tts", json={"text": phrase, "language": TTS_LANG[language]}),
            "answer synthesis",
        )
        response = core.post(
            f"/v1/investigations/{state['id']}/answers/voice",
            data={"question_id": question["id"], "participant_id": participant_id},
            files={"audio": ("answer.wav", answer_audio, "audio/wav")},
        )
        voiced = response_json(response)
        result = voiced["result"]
        state = result["state"]
        outcome = result["extraction"]["outcome"]
        voice_detail = {
            "stt": voiced["stt"]["transcript"],
            "language": voiced["stt"].get("detected_language"),
        }
    else:
        response = core.post(
            f"/v1/investigations/{state['id']}/answers",
            json={
                "question_id": question["id"],
                "participant_id": participant_id,
                "text": phrase,
            },
        )
        result = response_json(response)
        state = result["state"]
        outcome = result["extraction"]["outcome"]
        voice_detail = {}

    return state, {
        "question_id": question["id"],
        "participant_id": participant_id,
        "probe_id": action.get("probe_id"),
        "question": question["text"],
        "language": language,
        "card_label": card_label,
        "observed": observed,
        "said": said,
        "phrase": phrase,
        "outcome": outcome,
        "misreported": claim or (question.get("kind") != "challenge" and said != observed),
        "claim": claim,
        "claim_location": "IDF-2" if claim else None,
        "voice": voice_detail,
    }


def play_pending(
    core: httpx.Client,
    sim: httpx.Client,
    state: dict[str, Any],
    *,
    voice: bool = False,
    lies: dict[str, str] | None = None,
    variant: str = "honest",
    on_event: Callable[[dict[str, Any]], None] | None = None,
    max_steps: int = 30,
) -> tuple[dict[str, Any], int, int]:
    step = 0
    max_parallel_observed = 0
    while pending_questions(state):
        waiting = pending_questions(state)
        max_parallel_observed = max(max_parallel_observed, len(waiting))
        question = waiting[0]
        if on_event:
            on_event(
                {
                    "type": "question",
                    "step": step + 1,
                    "question": question,
                    "pending_count": len(waiting),
                    "state": state,
                }
            )
        state, detail = answer_question(
            core,
            sim,
            state,
            question,
            lies=lies,
            voice=voice,
            variant=variant,
        )
        step += 1
        if on_event:
            on_event({"type": "answer", "step": step, "detail": detail, "state": state})
        if step >= max_steps and pending_questions(state):
            raise RehearsalError(f"still investigating after {max_steps} answered questions")
    return state, step, max_parallel_observed


def repair_and_verify(
    core: httpx.Client,
    sim: httpx.Client,
    state: dict[str, Any],
    *,
    approver: httpx.Client | None = None,
    approver_id: str = "u_demo_approver",
    on_event: Callable[[dict[str, Any]], None] | None = None,
    voice: bool = False,
    lies: dict[str, str] | None = None,
) -> tuple[dict[str, Any], int, int]:
    top = state["belief"]["hypotheses"][0]["id"]
    target, separator, mode = top.partition(".")
    if not separator or mode != "tripped":
        raise RehearsalError(f"no breaker-reset action is indicated by {top}")
    url = f"/v1/investigations/{state['id']}/approvals"
    requested = response_json(
        core.post(
            url,
            json={"action": "reset_breaker", "target": target, "participant_id": "p_imran"},
        )
    )
    approval = requested["approvals"][-1]
    decision_client = approver or core
    decision: dict[str, Any] = {"decision": "approve", "approver_id": approver_id}
    headers = {"X-Pramana-CSRF": "1"} if approver is not None else None
    decided = response_json(
        decision_client.post(
            f"{url}/{approval['id']}/decision",
            json=decision,
            headers=headers,
        )
    )
    final_approval = next(
        (item for item in decided.get("approvals", []) if item.get("id") == approval["id"]),
        approval,
    )
    grant = response_json(
        core.post(f"{url}/{approval['id']}/capability", params={"participant_id": "p_imran"})
    )
    token = _token(core, state["id"], "p_imran")
    headers = {"Authorization": f"Bearer {token['token']}"}
    if not grant.get("location_id"):
        raise RehearsalError("approved action has no simulator location")
    response_json(
        sim.post(
            f"/sim/v1/scenarios/{token['scenario_id']}/move",
            json={"to": grant["location_id"]},
            headers=headers,
        )
    )
    response_json(
        sim.post(
            f"/sim/v1/scenarios/{token['scenario_id']}/act",
            json={
                "action": "reset_breaker",
                "target": target,
                "capability": grant["capability"],
            },
            headers=headers,
        )
    )
    state = response_json(
        core.post(
            f"/v1/investigations/{state['id']}/interventions",
            json={"approval_id": approval["id"], "participant_id": "p_imran"},
        )
    )
    if on_event:
        approvals = state.get("approvals", [])
        final_approval = next(
            (item for item in approvals if item.get("id") == approval["id"]),
            final_approval,
        )
        on_event(
            {
                "type": "approval",
                "approval_id": approval["id"],
                "approver_id": final_approval.get("approver_id") or approver_id,
                "label": approval.get("action_label", "Reset breaker"),
                "target": target,
            }
        )
        on_event({"type": "repair", "state": state, "grant": grant})
    state, step, max_parallel = play_pending(
        core,
        sim,
        state,
        voice=voice,
        lies=lies,
        on_event=on_event,
    )
    return state, step, max_parallel


def reveal_and_replay(core: httpx.Client, inv_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    revealed = response_json(core.post(f"/v1/investigations/{inv_id}/reveal"))
    replay = response_json(core.get(f"/v1/investigations/{inv_id}/replay"))
    return revealed, replay


def reveal_summary(state: dict[str, Any]) -> str:
    ground_truth = state.get("ground_truth", {})
    reveal = ground_truth.get("reveal", {})
    faults = reveal.get("fault_spec", {}).get("faults", [])
    return json.dumps(faults, ensure_ascii=False)
