"""Seeded benchmark scenarios and simulated participants.

The world uses the same physics as the simulator. Participants answer from the true world with
their *own* reliability, drawn per scenario from distributions that differ from what the engine
assumes (docs/EVALUATION.md §2): the engine is not rewarded for meeting only its own assumptions.
Answers use common random numbers: an answer depends only on (scenario seed, person, probe,
location, how many times they were asked), so every policy that asks the same thing hears the
same thing.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Literal

from pramana_contracts import Directness, Hedge, ParticipantSpec
from pramana_domain import NO_FAULT, DomainPack, World
from pramana_engine import CompiledModel, Engine, Evidence

Kind = Literal["single", "pair", "no_fault", "access_limited"]
KIND_MIX: list[tuple[Kind, float]] = [
    ("single", 0.65),
    ("pair", 0.15),
    ("no_fault", 0.05),
    ("access_limited", 0.15),
]

# Beta(a, b) for the true reliability of each skill and probe class (EVALUATION.md §2.2).
TRUE_RELIABILITY: dict[str, dict[str, tuple[float, float]]] = {
    "lay": {"device": (18, 2), "visual": (8, 3), "panel": (2, 2)},
    "access": {"device": (19, 1), "visual": (12, 2), "panel": (4, 3)},
    "technician": {"device": (38, 2), "visual": (30, 2), "panel": (48, 2)},
}
STUDENT_PLACES = [
    "F2_R205",
    "F2_R210",
    "F3_R304",
    "F3_R310",
    "F2_CORRIDOR",
    "F3_CORRIDOR",
    "F1_LOBBY",
]


def _stable_random(*key: object) -> random.Random:
    digest = hashlib.sha256("|".join(map(str, key)).encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


@dataclass(frozen=True)
class Person:
    spec: ParticipantSpec
    reliability: dict[str, float]
    hedge_p: float
    hearsay_p: float


@dataclass(frozen=True)
class Scenario:
    seed: int
    kind: Kind
    faults: tuple[tuple[str, str], ...]
    people: tuple[Person, ...]
    reporter: str
    true_decisions: frozenset[str]
    identifiable: bool | None
    """Whether the people present can, in principle, tell the true decision apart from every
    other decision. ``None`` for two-fault worlds (outside the model by design)."""

    @property
    def specs(self) -> list[ParticipantSpec]:
        return [p.spec for p in self.people]


def _person(pid: str, role: str, skill: str, loc: str, lang: str, rng: random.Random) -> Person:
    spec = ParticipantSpec.model_validate(
        {
            "id": pid,
            "display_name": pid.removeprefix("p_").replace("_", " ").title(),
            "roles": [role],
            "skill": skill,
            "location_id": loc,
            "languages": {"stt_candidates": ["hi-IN", "en-IN"], "template_language": lang},
        }
    )
    rel = {cls: rng.betavariate(*ab) for cls, ab in TRUE_RELIABILITY[skill].items()}
    return Person(spec, rel, hedge_p=0.2, hearsay_p=0.1 if skill == "lay" else 0.0)


def generate(pack: DomainPack, model: CompiledModel, seed: int) -> Scenario:
    rng = random.Random(seed)
    kind = rng.choices([k for k, _ in KIND_MIX], weights=[w for _, w in KIND_MIX])[0]
    catalogue = [(c, m) for c, m, _ in pack.fault_hypotheses()]
    if kind == "no_fault":
        faults: tuple[tuple[str, str], ...] = ()
    elif kind == "pair":
        a, b = rng.sample(catalogue, 2)
        faults = (a, b)
    else:
        faults = (rng.choice(catalogue),)
    world = World(pack, frozenset(faults))
    probe = pack.probe_by_id["internet_works"]
    affected = [loc for loc in STUDENT_PLACES if world.observe(probe, loc) == "no"]
    people = [
        _person(
            "p_reporter", "student", "lay", rng.choice(affected or STUDENT_PLACES), "hi-en", rng
        )
    ]
    for i in range(rng.randint(0, 2)):
        people.append(
            _person(
                f"p_student_{i + 1}", "student", "lay", rng.choice(STUDENT_PLACES), "hi-en", rng
            )
        )
    if kind != "access_limited":
        if rng.random() < 0.85:
            people.append(_person("p_guard", "guard", "access", "GUARD_DESK", "mr", rng))
        if rng.random() < 0.6:
            people.append(
                _person("p_electrician", "electrician", "technician", "MAINT_ROOM", "hi", rng)
            )
        if rng.random() < 0.4:
            people.append(_person("p_it", "it_tech", "technician", "MAINT_ROOM", "en", rng))
    hyp_ids = [f"{c}.{m}" for c, m in faults] or [NO_FAULT]
    true_decisions = frozenset(pack.decision_of[h] for h in hyp_ids)
    identifiable = (
        None if kind == "pair" else _identifiable(model, [p.spec for p in people], hyp_ids[0])
    )
    return Scenario(seed, kind, faults, tuple(people), "p_reporter", true_decisions, identifiable)


def _identifiable(model: CompiledModel, specs: list[ParticipantSpec], true_hyp: str) -> bool:
    """True if every hypothesis with a different decision predicts something different at a
    site someone present could observe (ignoring question budgets and noise)."""
    probe_specs = [s.model_copy(update={"question_budget": 20}) for s in specs]
    sites = {(a.probe_id, a.location_id) for a, _ in Engine(model, probe_specs).menu()}
    idx = [model.site_index[s] for s in sites]
    t = model.hypothesis_index(true_hyp)
    for h, hyp in enumerate(model.hypotheses):
        if hyp.faults is None or hyp.decision_class == model.hypotheses[t].decision_class:
            continue
        if all(model.predictions[h, i] == model.predictions[t, i] for i in idx):
            return False
    return True


class Answers:
    """Simulated participants answering from the true world (common random numbers)."""

    def __init__(self, pack: DomainPack, scenario: Scenario) -> None:
        self.pack = pack
        self.scenario = scenario
        self.world = World(pack, frozenset(scenario.faults))
        self.people = {p.spec.id: p for p in scenario.people}
        self._asked: dict[tuple[str, str, str], int] = {}

    def ask(self, participant_id: str, probe_id: str, location_id: str) -> Evidence:
        key = (participant_id, probe_id, location_id)
        k = self._asked.get(key, 0)
        self._asked[key] = k + 1
        person = self.people[participant_id]
        probe = self.pack.probe_by_id[probe_id]
        rng = _stable_random(self.scenario.seed, participant_id, probe_id, location_id, k)
        truth = self.world.observe(probe, location_id)
        if rng.random() < person.reliability[probe.probe_class]:
            said = truth
        else:
            said = rng.choice([o for o in probe.outcomes if o != truth])
        hedge = Hedge.CERTAIN
        if rng.random() < person.hedge_p:
            hedge = Hedge.UNSURE if rng.random() < 0.25 else Hedge.PROBABLE
        directness = Directness.HEARSAY if rng.random() < person.hearsay_p else Directness.DIRECT
        return Evidence(participant_id, probe_id, location_id, said, hedge, directness)

    def report(self) -> Evidence:
        """The reporter's initial complaint, as an answer to the intake probe."""
        reporter = self.people[self.scenario.reporter]
        return self.ask(reporter.spec.id, "internet_works", reporter.spec.location_id)
