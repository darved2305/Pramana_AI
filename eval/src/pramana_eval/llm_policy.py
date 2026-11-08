"""Policy B: an LLM choosing from the same action menu (docs/EVALUATION.md §3).

The model sees the documented site (rendered from the same pack the engine uses), the people,
the report, the full history of questions and answers, and the identical feasible menu. Each step
it returns strict JSON: a menu action id or "conclude", a decision class (or "abstain"), and a
confidence. The JSON schema restricts ids to the menu, so it cannot invent actions.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pramana_contracts import ProbeAction
from pramana_core.llm import LlmClient, LlmError
from pramana_domain import DomainPack, load_pack
from pramana_engine import Engine, EngineConfig, Evidence

from .policies import Conclusion, History, Step
from .scenarios import Scenario

SYSTEM = (
    "You coordinate a fault investigation in a building you cannot see. You can only ask the "
    "listed people to make the listed observations. Answers can be wrong: people misread "
    "lights and screens, guess, and relay rumours. Every question costs that person's time, "
    "so ask only what helps decide what to do. When you are confident enough, conclude with "
    'one decision class; if the evidence cannot settle it, conclude with "abstain". '
    "Reply only with the JSON object."
)


def render_site(pack: DomainPack) -> str:
    lines = ["COMPONENTS (dependencies):"]
    for c in pack.components:
        deps = [
            f"{k} {v}"
            for k, v in (
                ("power from", c.powered_by),
                ("PoE from", c.poe_from),
                ("uplink", c.uplink),
                ("hosted on", c.hosted_on),
                ("WAN", c.upstream),
            )
            if v
        ]
        at = f" at {c.location}" if c.location else ""
        fails = "/".join(m.id for m in c.failure_modes)
        lines.append(
            f"- {c.id} ({c.kind}{at}){': ' + ', '.join(deps) if deps else ''}"
            f"{' | can fail: ' + fails if fails else ''}"
        )
    lines.append("WI-FI COVERAGE (strongest AP first):")
    lines += [
        f"- {loc.id}: {', '.join(loc.wifi_coverage)}" for loc in pack.locations if loc.wifi_coverage
    ]
    lines.append("OBSERVATIONS (meaning of outcomes):")
    lines += [f"- {p.id}: {p.label}; outcomes {'/'.join(p.outcomes)}" for p in pack.probes]
    lines.append("DECISIONS (what to do, and the faults each one fixes):")
    lines += [f"- {d.id}: {d.label} [{', '.join(d.hypotheses)}]" for d in pack.decision_classes]
    return "\n".join(lines)


def _answer(ev: Evidence) -> str:
    tags = [
        t
        for t in (
            ev.hedge.value if ev.hedge.value != "certain" else "",
            "heard from someone else" if ev.directness.value == "hearsay" else "",
        )
        if t
    ]
    return ev.outcome + (f" ({', '.join(tags)})" if tags else "")


class LlmPolicy:
    def __init__(self, client: LlmClient, pack: DomainPack, name: str | None = None) -> None:
        self.client = client
        self.pack = pack
        self.name = name or f"B_llm[{client.model}]"
        self.config = EngineConfig()
        self._site = render_site(pack)
        self._scenario: Scenario | None = None
        self._report: Evidence | None = None
        self.errors = 0

    @classmethod
    def from_env(cls) -> LlmPolicy:  # pragma: no cover - convenience for notebooks
        provider = os.environ.get("BENCH_LLM_PROVIDER", "groq")
        model = os.environ.get("BENCH_LLM_MODEL") or None
        cache = Path(os.environ.get("BENCH_LLM_CACHE", ".cache/llm"))
        return cls(LlmClient(provider, model, cache_dir=cache), load_pack("campus_block_c"))

    def start(self, scenario: Scenario, report: Evidence | None = None) -> None:
        self._scenario = scenario
        self._report = report

    def next(self, engine: Engine, history: History) -> Step:
        assert self._scenario is not None
        menu = [a for a, _ in engine.menu()]
        costs = {(a.participant_id, a.probe_id, a.location_id): c for a, c in engine.menu()}
        ids = {f"a{i + 1}": a for i, a in enumerate(menu)}
        decisions = [d.id for d in self.pack.decision_classes]
        people = "\n".join(
            f"- {p.spec.id}: {p.spec.roles[0]} at {p.spec.location_id}"
            for p in self._scenario.people
        )
        rep = self._report
        report = (
            f"{rep.participant_id} at {rep.location_id} says internet_works = {_answer(rep)}"
            if rep
            else "a Wi-Fi problem was reported"
        )
        past = (
            "\n".join(
                f"{i + 1}. {a.participant_id} {a.probe_id}@{a.location_id} -> {_answer(ev)}"
                for i, (a, ev) in enumerate(history)
            )
            or "(none yet)"
        )
        options = "\n".join(
            f"{k}: {a.participant_id} checks {a.probe_id} at {a.location_id}"
            f"{' (must walk there)' if a.requires_move else ''}, "
            f"~{costs[(a.participant_id, a.probe_id, a.location_id)]:.0f}s"
            for k, a in ids.items()
        )
        user = (
            f"{self._site}\n\nPEOPLE:\n{people}\n\nREPORT: {report}\n\nANSWERS SO FAR:\n"
            f"{past}\n\nACTIONS YOU CAN TAKE NOW:\n{options or '(none)'}\n\n"
            f'Step {len(history) + 1}. Choose one action id, or "conclude".'
        )
        schema: dict[str, Any] = {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": [*ids, "conclude"]},
                "decision_class": {"type": "string", "enum": [*decisions, "abstain"]},
                "confidence": {"type": "number"},
            },
            "required": ["action", "decision_class", "confidence"],
            "additionalProperties": False,
        }
        try:
            out = self.client.complete_json(
                [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                schema,
                name="next_step",
            ).data
        except LlmError:
            self.errors += 1
            return Conclusion(None, 0.0, failed=True)
        confidence = max(0.0, min(1.0, float(out.get("confidence", 0.0))))
        action = out.get("action")
        if action != "conclude" and action in ids:
            chosen: ProbeAction = ids[action]
            return chosen
        decision = out.get("decision_class")
        return Conclusion(None if decision in (None, "abstain") else str(decision), confidence)
