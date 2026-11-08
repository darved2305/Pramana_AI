"""Model health check: can this site's people and checks actually diagnose its faults?

Run it on a draft site model before publishing (docs/PRODUCTION.md §8.6). It is pure (no I/O),
so the core can run it on drafts and the benchmark harness can run it offline. It answers, for the
organization's own people and roles:

* **static findings**, exact and noise-free: faults nobody could ever notice, faults that need
  different decisions but look identical to everyone available, checks nobody can make,
  repairs nobody present may carry out, repairs that cannot be verified independently, and
  decisions the engine could reach without knowing which component to repair;
* **simulated investigations**, with answer noise drawn from distributions that differ from
  what the engine assumes (docs/EVALUATION.md §2): per fault, how often the engine reaches the
  right decision, abstains or is wrong, and how many questions and minutes it takes.

Abstaining is the right outcome when the available people cannot tell a fault apart; the
findings say what would fix that (another person, access to a place, another check).
"""

from __future__ import annotations

import hashlib
import random
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from pramana_contracts import Directness, Hedge, ParticipantSpec, PlanKind
from pramana_domain import NO_FAULT, DomainPack, World

from .engine import Engine, Evidence
from .model import CompiledModel, compile_pack

Severity = Literal["error", "warning"]
MAX_STEPS = 30

TRUE_RELIABILITY: dict[str, dict[str, tuple[float, float]]] = {
    "lay": {"device": (18, 2), "visual": (8, 3), "panel": (2, 2)},
    "access": {"device": (19, 1), "visual": (12, 2), "panel": (4, 3)},
    "technician": {"device": (38, 2), "visual": (30, 2), "panel": (48, 2)},
}
"""Beta(a, b) of each skill's true reliability per probe class (docs/EVALUATION.md §2.2). They
differ from what the engine assumes, so the check does not only reward its own assumptions."""


def _stable_random(*key: object) -> random.Random:
    digest = hashlib.sha256("|".join(map(str, key)).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


class _NoisyPeople:
    """Simulated people answering from a hypothetical world with their own reliability."""

    def __init__(
        self, pack: DomainPack, world: World, people: list[ParticipantSpec], key: str
    ) -> None:
        self.pack, self.world, self.key = pack, world, key
        rng = random.Random(key)
        self.reliability = {
            p.id: {cls: rng.betavariate(*ab) for cls, ab in TRUE_RELIABILITY[str(p.skill)].items()}
            for p in people
        }
        self.lay = {p.id for p in people if str(p.skill) == "lay"}
        self._asked: dict[tuple[str, str, str], int] = {}

    def ask(self, participant_id: str, probe_id: str, location_id: str) -> Evidence:
        site = (participant_id, probe_id, location_id)
        k = self._asked.get(site, 0)
        self._asked[site] = k + 1
        rng = _stable_random(self.key, *site, k)
        probe = self.pack.probe_by_id[probe_id]
        truth = self.world.observe(probe, location_id)
        if rng.random() < self.reliability[participant_id][probe.probe_class]:
            said = truth
        else:
            said = rng.choice([o for o in probe.outcomes if o != truth])
        hedge = Hedge.CERTAIN
        if rng.random() < 0.2:
            hedge = Hedge.UNSURE if rng.random() < 0.25 else Hedge.PROBABLE
        hearsay = participant_id in self.lay and rng.random() < 0.1
        directness = Directness.HEARSAY if hearsay else Directness.DIRECT
        return Evidence(participant_id, probe_id, location_id, said, hedge, directness)


@dataclass(frozen=True)
class Finding:
    severity: Severity
    code: str
    message: str


@dataclass(frozen=True)
class FaultResult:
    hypothesis: str
    label: str
    decision: str
    reportable: bool
    """Someone present would notice a symptom where they are."""
    episodes: int = 0
    correct: int = 0
    abstained: int = 0
    wrong: int = 0
    mean_questions: float | None = None
    mean_effort_s: float | None = None


@dataclass(frozen=True)
class HealthReport:
    pack: str
    version: str
    people: int
    findings: list[Finding] = field(default_factory=list)
    faults: list[FaultResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(f.severity == "error" for f in self.findings)

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "ok": self.ok}


def check(
    pack: DomainPack,
    people: list[ParticipantSpec],
    *,
    episodes: int = 20,
    seed: int = 0,
    model: CompiledModel | None = None,
) -> HealthReport:
    """Static findings plus ``episodes`` simulated investigations per single fault."""
    model = model or compile_pack(pack)
    findings = _static_findings(pack, model, people)
    results = [
        _simulate(pack, model, people, hid, episodes, seed)
        for hid in [f"{c}.{m}" for c, m, _ in pack.fault_hypotheses()] + [NO_FAULT]
    ]
    for r in results:
        if r.episodes and r.wrong / r.episodes > 0.2:
            findings.append(
                Finding(
                    "warning",
                    "OFTEN_WRONG",
                    f"{r.label}: the wrong decision in {r.wrong} of {r.episodes} simulated "
                    "investigations. Add a more reliable check or a person who can make one.",
                )
            )
    return HealthReport(pack.pack, pack.version, len(people), findings, results)


# -- static analysis --------------------------------------------------------------------------


def _observable(model: CompiledModel, people: list[ParticipantSpec]) -> set[int]:
    """Indices of sites someone present could observe (ignoring question budgets)."""
    roomy = [p.model_copy(update={"question_budget": 20, "available": True}) for p in people]
    return {model.site_index[(a.probe_id, a.location_id)] for a, _ in Engine(model, roomy).menu()}


def _static_findings(
    pack: DomainPack, model: CompiledModel, people: list[ParticipantSpec]
) -> list[Finding]:
    out: list[Finding] = []
    if not people:
        return [Finding("error", "NO_PEOPLE", "Add at least one person who can be asked.")]
    observable = _observable(model, people)
    singles = [
        (i, h)
        for i, h in enumerate(model.hypotheses)
        if h.faults is not None and len(h.faults) <= 1
    ]
    no_fault = model.hypothesis_index(NO_FAULT)
    held_roles = {str(r) for p in people for r in p.roles}

    for i, h in singles:
        if i != no_fault and (model.predictions[i] == model.predictions[no_fault]).all():
            out.append(
                Finding(
                    "error",
                    "SILENT_FAULT",
                    f"{h.label}: no check in the model would look any different. "
                    "Add a check that this fault changes.",
                )
            )

    # Equal predictions at every observable check is an equivalence: group the look-alikes.
    seen_sites = sorted(observable)
    groups: dict[tuple[int, ...], list[int]] = {}
    for i, _ in singles:
        groups.setdefault(tuple(int(model.predictions[i, s]) for s in seen_sites), []).append(i)
    for members in groups.values():
        decisions = {model.hypotheses[i].decision_class for i in members}
        if len(decisions) < 2:
            continue
        labels = ", ".join(model.hypotheses[i].label for i in members)
        splitting = [
            s
            for s in range(len(model.sites))
            if len({int(model.predictions[i, s]) for i in members}) > 1
        ]
        hint = "; ".join(_describe_site(pack, model.sites[s]) for s in splitting[:4])
        out.append(
            Finding(
                "error",
                "INDISTINGUISHABLE",
                f"These look the same to everyone available but need {len(decisions)} different "
                f"decisions: {labels}. "
                + (f"Someone who can check {hint} would tell them apart." if hint else ""),
            )
        )

    unreachable: dict[str, list[str]] = {}
    for s, (probe_id, loc) in enumerate(model.sites):
        if s not in observable:
            unreachable.setdefault(probe_id, []).append(pack.location_by_id[loc].label.en)
    for probe_id, places in unreachable.items():
        probe = pack.probe_by_id[probe_id]
        roles = "anyone" if "any" in probe.roles else " or ".join(probe.roles)
        out.append(
            Finding(
                "warning",
                "UNREACHABLE_CHECK",
                f"Nobody available ({roles}) can check '{probe.label}' at {', '.join(places)}.",
            )
        )

    for act in pack.actions:
        if not held_roles & set(act.roles):
            out.append(
                Finding(
                    "warning",
                    "NO_ONE_TO_REPAIR",
                    f"Nobody available may '{act.label}' (needs {', '.join(act.roles)}). "
                    "The investigation can decide, but the repair has to wait.",
                )
            )

    for d in pack.decision_classes:
        targets: dict[str, set[str]] = {}
        for hid in d.hypotheses:
            if hid == NO_FAULT:
                continue
            cid, _, mode = hid.rpartition(".")
            kind = pack.component_by_id[cid].kind
            for act in pack.actions:
                if act.target_kind == kind and act.fixes == mode and d.id in act.decision_classes:
                    targets.setdefault(act.id, set()).add(cid)
        for act_id, comps in targets.items():
            if len(comps) > 1:
                out.append(
                    Finding(
                        "warning",
                        "SPLIT_TARGET_DECISION",
                        f"Decision '{d.label}' covers '{act_id}' on {', '.join(sorted(comps))}. "
                        "The engine can reach it without knowing which one to repair, and the "
                        "repair then cannot be verified. Use one decision per target.",
                    )
                )

    for act in pack.actions:
        for c in pack.components:
            if c.kind != act.target_kind or act.fixes not in {m.id for m in c.failure_modes}:
                continue
            i = model.hypothesis_index(f"{c.id}.{act.fixes}")
            changes = [
                s for s in observable if model.predictions[i, s] != model.predictions[no_fault, s]
            ]
            if len(changes) < 2:
                out.append(
                    Finding(
                        "warning",
                        "WEAK_VERIFICATION",
                        f"After '{act.label}' on {c.id}, at most {len(changes)} available "
                        "check(s) would show the difference, so a repair can rarely be verified "
                        "from new evidence. Add another check downstream of it.",
                    )
                )
    return out


def _describe_site(pack: DomainPack, site: tuple[str, str]) -> str:
    probe = pack.probe_by_id[site[0]]
    roles = "anyone" if "any" in probe.roles else " or ".join(probe.roles)
    return f"'{probe.label}' at {pack.location_by_id[site[1]].label.en} ({roles})"


# -- simulation -------------------------------------------------------------------------------


def _report_site(
    pack: DomainPack, world: World, healthy: World, people: list[ParticipantSpec]
) -> tuple[ParticipantSpec, str] | None:
    """A person who would notice something wrong where they are, preferring lay reporters."""
    ordered = sorted(people, key=lambda p: (str(p.skill) != "lay", p.id))
    for person in ordered:
        roles = {str(r) for r in person.roles}
        for probe in pack.probes:
            binding = probe.binding_at(person.location_id)
            if binding is None or not probe.allows(roles):
                continue
            here = person.location_id
            if world.observe(probe, here) != healthy.observe(probe, here):
                return person, probe.id
    return None


def _simulate(
    pack: DomainPack,
    model: CompiledModel,
    people: list[ParticipantSpec],
    hid: str,
    episodes: int,
    seed: int,
) -> FaultResult:
    h = model.hypotheses[model.hypothesis_index(hid)]
    assert h.faults is not None
    assert h.decision_class is not None
    faults = frozenset(h.faults)
    world, healthy = World(pack, faults), World(pack, frozenset())
    if hid == NO_FAULT:
        # A false alarm: the first lay person reports a symptom that is not there.
        lay = [p for p in people if str(p.skill) == "lay"] or people
        site: tuple[ParticipantSpec, str] | None = None
        for probe in pack.probes:
            if (
                lay
                and probe.binding_at(lay[0].location_id)
                and probe.allows({str(r) for r in lay[0].roles})
            ):
                site = (lay[0], probe.id)
                break
    else:
        site = _report_site(pack, world, healthy, people)
    if site is None:
        return FaultResult(hid, h.label, h.decision_class, reportable=False)
    reporter, report_probe = site

    correct = abstained = wrong = 0
    questions: list[int] = []
    effort: list[float] = []
    for n in range(episodes):
        answers = _NoisyPeople(pack, world, people, f"{seed}:{hid}:{n}")
        engine = Engine(model, people)
        report = answers.ask(reporter.id, report_probe, reporter.location_id)
        if hid == NO_FAULT:
            healthy_out = healthy.observe(pack.probe_by_id[report_probe], reporter.location_id)
            wrong_out = [o for o in pack.probe_by_id[report_probe].outcomes if o != healthy_out]
            report = Evidence(reporter.id, report_probe, reporter.location_id, wrong_out[0])
        engine.observe(report)
        asked, spent = 0, 0.0
        decision: str | None = None
        for _ in range(MAX_STEPS):
            plan = engine.plan()
            if plan.kind != PlanKind.ASK or plan.action is None:
                decision = plan.decision_class if plan.kind == PlanKind.DECIDE else None
                break
            a = plan.action
            costs = {(x.participant_id, x.probe_id, x.location_id): c for x, c in engine.menu()}
            spent += costs.get((a.participant_id, a.probe_id, a.location_id), 0.0)
            engine.record_question(a.participant_id)
            engine.observe(answers.ask(a.participant_id, a.probe_id, a.location_id))
            asked += 1
        questions.append(asked)
        effort.append(spent)
        if decision is None:
            abstained += 1
        elif decision == h.decision_class:
            correct += 1
        else:
            wrong += 1
    return FaultResult(
        hid,
        h.label,
        h.decision_class,
        reportable=True,
        episodes=episodes,
        correct=correct,
        abstained=abstained,
        wrong=wrong,
        mean_questions=statistics.fmean(questions) if questions else None,
        mean_effort_s=statistics.fmean(effort) if effort else None,
    )


def default_cast(pack: DomainPack) -> list[ParticipantSpec]:
    """One person per role, for checking a draft before its real people are entered.

    Everyday users stand where the first service is experienced; everyone else at the first
    unrestricted place, from where they can walk.
    """
    open_places = [loc.id for loc in pack.locations if not loc.restricted]
    hub = open_places[0] if open_places else pack.locations[0].id
    served = next(
        (b.at for p in pack.probes if "any" in p.roles for b in p.observes),
        hub,
    )
    return [
        ParticipantSpec.model_validate(
            {
                "id": f"p_{role.id}"[:64],
                "display_name": role.label,
                "roles": [role.id],
                "skill": role.skill,
                "location_id": served if role.skill == "lay" else hub,
                "languages": {"stt_candidates": ["hi-IN", "en-IN"]},
            }
        )
        for role in pack.role_catalogue.values()
    ]
