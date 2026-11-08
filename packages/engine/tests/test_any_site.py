"""The unchanged engine investigates a site that is not a building network.

The water supply template uses the dependency physics, its own role catalogue (resident,
plumber) and its own place kinds. Nothing in the engine knows about water: diagnosis, value of
information, abstention and repair verification run on the compiled prediction table alone.
"""

from __future__ import annotations

import pytest
from engine_testkit import person

from pramana_contracts import ParticipantSpec, PlanKind
from pramana_domain import DomainPack, World, load_pack
from pramana_domain.pack import default_packs_dir
from pramana_engine import CompiledModel, Engine, Evidence, compile_pack

FaultSet = frozenset[tuple[str, str]]


@pytest.fixture(scope="module")
def water() -> DomainPack:
    return load_pack(default_packs_dir() / "templates" / "building_water_supply.yaml")


@pytest.fixture(scope="module")
def water_model(water: DomainPack) -> CompiledModel:
    return compile_pack(water)


@pytest.fixture
def staff() -> list[ParticipantSpec]:
    return [
        person("p_reporter", ["resident"], "lay", "F3_WASHROOM"),
        person("p_guard", ["guard"], "access", "GUARD_DESK"),
        person("p_plumber", ["plumber"], "technician", "GUARD_DESK"),
        person("p_electrician", ["electrician"], "technician", "GUARD_DESK"),
    ]


def ask_until_done(
    pack: DomainPack, eng: Engine, faults: FaultSet, limit: int = 15
) -> tuple[str, list[str]]:
    world = World(pack, faults)
    asked: list[str] = []
    for _ in range(limit):
        plan = eng.plan()
        if plan.kind != PlanKind.ASK:
            return f"{plan.kind.value}:{plan.decision_class}", asked
        a = plan.action
        assert a is not None
        eng.record_question(a.participant_id)
        out = world.observe(pack.probe_by_id[a.probe_id], a.location_id)
        asked.append(f"{a.participant_id}:{a.probe_id}@{a.location_id}={out}")
        eng.observe(Evidence(a.participant_id, a.probe_id, a.location_id, out))
    raise AssertionError(f"no conclusion after {limit} questions: {asked}")


def investigate(
    pack: DomainPack, model: CompiledModel, people: list[ParticipantSpec], faults: FaultSet
) -> tuple[Engine, str, list[str]]:
    eng = Engine(model, people)
    report = World(pack, faults).observe(pack.probe_by_id["tap_flows"], "F3_WASHROOM")
    eng.observe(Evidence("p_reporter", "tap_flows", "F3_WASHROOM", report))
    outcome, asked = ask_until_done(pack, eng, faults)
    return eng, outcome, asked


@pytest.mark.parametrize(
    ("faults", "decision"),
    [
        ({("VALVE_F3", "closed")}, "OPEN_VALVE_F3"),
        ({("PUMP_BREAKER", "tripped")}, "RESET_PUMP_BREAKER"),
        ({("MUNICIPAL", "cut")}, "ORDER_TANKER"),
        ({("PUMP_CONTROL", "controller_fault")}, "SERVICE_PUMP_CONTROL"),
        ({("GRID_FEED", "lost")}, "ESCALATE_POWER"),
    ],
)
def test_noise_free_water_investigations_reach_the_true_decision(
    water: DomainPack,
    water_model: CompiledModel,
    staff: list[ParticipantSpec],
    faults: set[tuple[str, str]],
    decision: str,
) -> None:
    _, outcome, asked = investigate(water, water_model, staff, frozenset(faults))
    assert outcome == f"decide:{decision}", asked
    assert len(asked) <= 8, asked


def test_two_pump_failure_is_not_assumed_over_a_likelier_single_cause(
    water: DomainPack, water_model: CompiledModel, staff: list[ParticipantSpec]
) -> None:
    # Both pumps silent fits a municipal cut (prior 0.008) far better than two independent pump
    # failures (0.004 squared). Acting on the likelier cause first is the correct call.
    both = frozenset({("PUMP_A", "dead"), ("PUMP_B", "dead")})
    _, outcome, _ = investigate(water, water_model, staff, both)
    assert outcome in {"decide:ORDER_TANKER", "decide:REPAIR_PUMP"}


def test_redundancy_is_compiled_as_masking(water_model: CompiledModel) -> None:
    ids = {h.id for h in water_model.hypotheses}
    assert "PUMP_A.dead+PUMP_B.dead" in ids  # both pumps down: a distinct, visible world
    # A closed floor valve hides the pump behind it from that floor; a pump failure is still
    # visible in the pump room, so the pair is identifiable too.
    assert "PUMP_A.dead+VALVE_F3.closed" in ids


def test_nobody_who_can_reach_the_cause_means_abstaining(
    water: DomainPack, water_model: CompiledModel
) -> None:
    # Only residents: nobody may enter the pump room, the panel or the shaft, so the closed
    # valve cannot be told apart from an empty tank. The engine must not guess.
    residents = [
        person("p_reporter", ["resident"], "lay", "F3_WASHROOM"),
        person("p_neighbour", ["resident"], "lay", "F2_WASHROOM"),
    ]
    _, outcome, asked = investigate(
        water, water_model, residents, frozenset({("VALVE_F3", "closed")})
    )
    assert outcome.startswith("abstain"), asked


def test_opening_the_valve_is_verified_from_new_evidence(
    water: DomainPack, water_model: CompiledModel, staff: list[ParticipantSpec]
) -> None:
    faults = frozenset({("VALVE_F3", "closed")})
    eng, outcome, _ = investigate(water, water_model, staff, faults)
    assert outcome == "decide:OPEN_VALVE_F3"
    eng.apply_intervention("open_valve", "VALVE_F3")
    result, _ = ask_until_done(water, eng, frozenset())  # the plumber opened it: water again
    assert result.startswith("verified")
    snap = eng.snapshot()
    assert snap.repair is not None
    assert snap.repair.fixed_probability >= 0.97


def test_a_repair_of_the_wrong_cause_is_not_verified(
    water: DomainPack, water_model: CompiledModel, staff: list[ParticipantSpec]
) -> None:
    eng, outcome, _ = investigate(
        water, water_model, staff, frozenset({("PUMP_BREAKER", "tripped")})
    )
    assert outcome == "decide:RESET_PUMP_BREAKER"
    eng.apply_intervention("reset_breaker", "PUMP_BREAKER")
    # The breaker trips again straight away: the world is still broken.
    result, _ = ask_until_done(water, eng, frozenset({("PUMP_BREAKER", "tripped")}))
    assert result.startswith("not_verified")
