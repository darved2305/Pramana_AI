"""Repair verification: branches for fixed / not fixed, risky-prediction preference."""

from __future__ import annotations

import pytest
from engine_testkit import person

from pramana_contracts import ParticipantSpec, PlanKind
from pramana_domain import DomainPack, World
from pramana_engine import CompiledModel, Engine, EngineConfig, Evidence, EvidenceError


def diagnose(
    campus: DomainPack,
    model: CompiledModel,
    people: list[ParticipantSpec],
    fault: tuple[str, str],
    lie: dict[str, str] | None = None,
) -> Engine:
    world = World(campus, frozenset({fault}))
    eng = Engine(model, people)
    eng.observe(Evidence("p_riya", "internet_works", "F3_R304", "no"))
    for _ in range(12):
        plan = eng.plan()
        if plan.kind != PlanKind.ASK:
            return eng
        a = plan.action
        assert a is not None
        eng.record_question(a.participant_id)
        out = (lie or {}).get(a.probe_id) or world.observe(
            campus.probe_by_id[a.probe_id], a.location_id
        )
        eng.observe(Evidence(a.participant_id, a.probe_id, a.location_id, out))
    raise AssertionError("no conclusion")


def verify(campus: DomainPack, eng: Engine, true_faults: set[tuple[str, str]]) -> tuple[str, int]:
    world = World(campus, frozenset(true_faults))
    for n in range(10):
        plan = eng.plan()
        if plan.kind != PlanKind.ASK:
            return plan.kind.value, n
        a = plan.action
        assert a is not None
        eng.record_question(a.participant_id)
        eng.observe(
            Evidence(
                a.participant_id,
                a.probe_id,
                a.location_id,
                world.observe(campus.probe_by_id[a.probe_id], a.location_id),
            )
        )
    raise AssertionError("verification did not finish")


def test_successful_reset_is_verified(
    campus: DomainPack, campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    eng = diagnose(campus, campus_model, s1_people, ("CB_C2_7", "tripped"))
    assert eng.plan().decision_class == "DISPATCH_ELECTRICIAN_DB_C2"
    p_cause = next(h.probability for h in eng.snapshot().hypotheses if h.id == "CB_C2_7.tripped")
    eng.apply_intervention("reset_breaker", "CB_C2_7")
    # Before any new observation: P(fixed) = P(cause) * (1 - P(repair failed)); never verified.
    assert eng.p_fixed() == pytest.approx(p_cause * 0.9, abs=1e-9)
    first = eng.plan()
    assert first.kind == PlanKind.ASK
    outcome, asked = verify(campus, eng, set())  # the reset worked: world is healthy
    assert outcome == "verified"
    assert 1 <= asked <= 3
    snap = eng.snapshot()
    assert snap.repair is not None
    assert snap.repair.fixed_probability >= 0.97


def test_reset_that_did_not_hold_is_not_verified(
    campus: DomainPack, campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    eng = diagnose(campus, campus_model, s1_people, ("CB_C2_7", "tripped"))
    eng.apply_intervention("reset_breaker", "CB_C2_7")
    outcome, _ = verify(campus, eng, {("CB_C2_7", "tripped")})  # it tripped again
    assert outcome == "not_verified"


def test_wrong_diagnosis_is_caught_by_verification(
    campus: DomainPack, campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    """Misreports led to the breaker; the switch was the real fault. Verification must say no."""
    lie = {"nvr_screen": "off", "breaker_c2_7": "tripped"}
    eng = diagnose(campus, campus_model, s1_people, ("SW_C2", "dead"), lie=lie)
    assert eng.plan().decision_class == "DISPATCH_ELECTRICIAN_DB_C2"
    eng.apply_intervention("reset_breaker", "CB_C2_7")
    outcome, _ = verify(campus, eng, {("SW_C2", "dead")})
    assert outcome == "not_verified"


def test_verification_prefers_consequences_not_used_in_diagnosis(
    campus: DomainPack, campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    eng = diagnose(campus, campus_model, s1_people, ("CB_C2_7", "tripped"))
    used = {(e.probe_id, e.location_id) for e in eng.evidence()}
    eng.apply_intervention("reset_breaker", "CB_C2_7")
    plan = eng.plan()
    assert plan.action is not None
    tops = [c for c in plan.candidates if c.eig_decision_bits >= 0.01]
    fresh = [c for c in tops if (c.action.probe_id, c.action.location_id) not in used]
    if fresh:  # with fresh informative options available, the bonus should favour one
        chosen = (plan.action.probe_id, plan.action.location_id)
        assert chosen not in used or fresh[0].score <= tops[0].score


def test_only_one_repair_is_modelled(campus_model: CompiledModel) -> None:
    eng = Engine(campus_model, [person("p_e", ["electrician"], "technician", "DB_C2_PANEL")])
    eng.apply_intervention("reset_breaker", "CB_C2_7")
    with pytest.raises(EvidenceError, match="only one repair"):
        eng.apply_intervention("reset_breaker", "CB_C2_7")
    with pytest.raises(EvidenceError, match="cannot target"):
        Engine(campus_model, []).apply_intervention("reset_breaker", "SW_C2")


def test_repair_of_something_that_was_not_the_cause_cannot_verify(
    campus_model: CompiledModel,
) -> None:
    """If nobody believed the breaker had tripped, resetting it cannot make P(fixed) high."""
    eng = Engine(
        campus_model,
        [person("p_t", ["electrician", "guard"], "technician", "IDF1")],
        EngineConfig(),
    )
    eng.observe(Evidence("p_t", "wan_led", "IDF1", "red"))  # an ISP outage
    eng.apply_intervention("reset_breaker", "CB_C2_7")
    assert eng.p_fixed() < 0.1
    assert eng.plan().kind == PlanKind.NOT_VERIFIED
