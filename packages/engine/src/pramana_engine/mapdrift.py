"""Map-drift discovery: does the testimony fit better if the site's map is wrong? (USP_LAB U11)

Advisory only. For the most likely single-link mistakes in the documented map (one component
actually fed by a different component of the same kind), it re-explains the evidence so far on
that altered map, in a separate engine, and compares how well each map explains what people said.
Documented maps have a strong prior and every altered map a small one, so one fault plus one
documentation error must beat every explanation on the documented map, including two faults.

Nothing here touches the investigation's engine, its belief, its events or its model.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Literal

from pydantic import ValidationError

from pramana_domain import DomainPack
from pramana_domain.pack import NETWORK_FIELDS

from .engine import Engine
from .model import compile_pack

DRIFT_PRIOR = 0.005
"""Prior of each single altered link. Small, so the documented map wins unless evidence demands."""
MIN_EVIDENCE = 3
MAX_VARIANTS = 40
MAX_ALTERNATIVES_PER_LINK = 4
SHOW_FROM = 0.5
"""Only propose a documentation change when the altered map is more likely than not."""


@dataclass(frozen=True)
class DriftFinding:
    component: str
    component_label: str
    documented: str
    documented_label: str
    proposed: str
    proposed_label: str
    probability: float
    best_fault: str
    best_fault_label: str


@dataclass(frozen=True)
class DriftReport:
    status: Literal["ok", "not_enough_evidence", "repair_in_progress"]
    variants_checked: int
    findings: list[DriftFinding]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _links(pack: DomainPack) -> list[tuple[str, str, int | None, str]]:
    """Every single-parent link: (component, field, ``requires`` index, documented parent)."""
    links: list[tuple[str, str, int | None, str]] = []
    for c in pack.components:
        for f in NETWORK_FIELDS:
            parent = getattr(c, f)
            if parent is not None:
                links.append((c.id, f, None, parent))
        for i, req in enumerate(c.requires):
            if isinstance(req, str):
                links.append((c.id, "requires", i, req))
    return sorted(links, key=lambda x: (x[0], x[1], x[2] if x[2] is not None else -1))


def _rewired(
    pack: DomainPack, component: str, field: str, index: int | None, alternative: str
) -> DomainPack | None:
    dump = pack.model_dump(mode="python", by_alias=True)
    for raw in dump["components"]:
        if raw["id"] == component:
            if index is None:
                raw[field] = alternative
            else:
                raw["requires"][index] = alternative
            break
    try:
        return DomainPack.model_validate(dump, by_alias=True, by_name=True)
    except ValidationError:
        return None  # for example, the altered link would close a cycle


def _variants(pack: DomainPack) -> list[tuple[str, str, str, DomainPack]]:
    out: list[tuple[str, str, str, DomainPack]] = []
    by_id = pack.component_by_id
    for component, field, index, parent in _links(pack):
        kind = by_id[parent].kind
        alternatives = sorted(
            c.id for c in pack.components if c.kind == kind and c.id not in (parent, component)
        )[:MAX_ALTERNATIVES_PER_LINK]
        for alt in alternatives:
            if len(out) >= MAX_VARIANTS:
                return out
            variant = _rewired(pack, component, field, index, alt)
            if variant is not None:
                out.append((component, parent, alt, variant))
    return out


def map_drift(engine: Engine) -> DriftReport:
    """Altered maps that explain the evidence better than the documented one, best first."""
    pack = engine.model.pack
    if engine._repair is not None:
        return DriftReport("repair_in_progress", 0, [])
    evidence = list(engine.evidence())
    if len(evidence) < MIN_EVIDENCE:
        return DriftReport("not_enough_evidence", 0, [])

    documented = engine.log_marginal()
    scored: list[tuple[float, str, str, str, str]] = []
    people = [state.spec for state in engine.participants.values()]
    variants = _variants(pack)
    for component, parent, alternative, variant in variants:
        replay = Engine(compile_pack(variant, pairs=False), people, engine.cfg)
        for ev in evidence:
            replay.observe(ev)
        p = replay.posterior()
        best = max(
            (i for i, h in enumerate(replay.model.hypotheses) if h.faults and len(h.faults) == 1),
            key=lambda i: float(p[i]),
            default=None,
        )
        if best is None:
            continue
        scored.append(
            (
                replay.log_marginal(),
                component,
                parent,
                alternative,
                replay.model.hypotheses[best].id,
            )
        )

    # Normalise documented + altered maps in log space, with the fixed small prior per variant.
    floor = max([documented, *[s[0] for s in scored]])
    remaining = max(1.0 - DRIFT_PRIOR * len(scored), 0.0)
    documented_weight = remaining * math.exp(documented - floor)
    weights = [DRIFT_PRIOR * math.exp(s[0] - floor) for s in scored]
    total = documented_weight + sum(weights)

    findings: list[DriftFinding] = []
    label = pack.component_by_id
    for s, w in sorted(zip(scored, weights, strict=True), key=lambda x: -x[1]):
        probability = w / total
        if probability < SHOW_FROM:
            continue
        marginal, component, parent, alternative, fault = s
        del marginal
        fault_h = next(h for h in engine.model.hypotheses if h.id == fault)
        findings.append(
            DriftFinding(
                component,
                label[component].label,
                parent,
                label[parent].label,
                alternative,
                label[alternative].label,
                probability,
                fault,
                fault_h.label,
            )
        )
    return DriftReport("ok", len(scored), findings)
