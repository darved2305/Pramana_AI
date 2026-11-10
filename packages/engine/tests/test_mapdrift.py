"""Map drift proposes a documentation fix when, and only when, the evidence demands one."""

from __future__ import annotations

import numpy as np

from pramana_contracts import ParticipantSpec, PlanKind
from pramana_domain import DomainPack, World
from pramana_engine import CompiledModel, Engine, Evidence, map_drift
from pramana_engine.mapdrift import _variants


def question(engine: Engine, truth: World, steps: int) -> Engine:
    """Ask what the engine would ask, answered truthfully from a given world."""
    pack = engine.model.pack
    for _ in range(steps):
        plan = engine.plan()
        if plan.kind != PlanKind.ASK or plan.action is None:
            break
        a = plan.action
        outcome = truth.observe(pack.probe_by_id[a.probe_id], a.location_id)
        engine.record_question(a.participant_id)
        engine.observe(Evidence(a.participant_id, a.probe_id, a.location_id, outcome))
    return engine


def test_correct_map_proposes_nothing_and_stays_untouched(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    pack = campus_model.pack
    engine = Engine(campus_model, s1_people)
    question(engine, World(pack, frozenset({("CB_C2_7", "tripped")})), 12)
    before = engine.posterior().copy()
    log_before = list(engine.evidence())
    report = map_drift(engine)
    assert report.status == "ok"
    assert report.variants_checked > 0
    assert report.findings == []
    assert np.array_equal(engine.posterior(), before)
    assert engine.evidence() == log_before


def test_a_wrong_link_in_the_map_is_found(
    campus: DomainPack, campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    # True building: one link is not as documented, and one component behind it has failed.
    found = False
    for component, parent, alternative, truth in _variants(campus):
        fault = next(
            (
                (c.id, m.id if hasattr(m, "id") else m.mode)
                for c in truth.components
                if c.id == alternative
                for m in c.failure_modes
            ),
            None,
        )
        if fault is None:
            continue
        engine = Engine(campus_model, s1_people)
        question(engine, World(truth, frozenset({fault})), 14)
        report = map_drift(engine)
        if any(f.component == component and f.proposed == alternative for f in report.findings):
            assert report.findings[0].probability >= 0.5
            assert report.findings[0].documented == parent
            found = True
            break
    assert found


def test_true_faults_on_the_correct_map_raise_no_false_alarm(
    campus: DomainPack, campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    singles = [h.faults[0] for h in campus_model.hypotheses if h.faults and len(h.faults) == 1]
    for fault in singles[:: max(1, len(singles) // 8)][:8]:
        engine = Engine(campus_model, s1_people)
        question(engine, World(campus, frozenset({fault})), 14)
        assert map_drift(engine).findings == [], fault


def test_too_little_evidence_is_said_plainly(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    assert map_drift(Engine(campus_model, s1_people)).status == "not_enough_evidence"
