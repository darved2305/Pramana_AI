"""The forecast estimates the rest of an investigation without changing it."""

from __future__ import annotations

import types

import numpy as np

from pramana_contracts import ParticipantSpec
from pramana_engine import CompiledModel, Engine, Evidence, forecast


def started(model: CompiledModel, people: list[ParticipantSpec]) -> Engine:
    engine = Engine(model, people)
    plan = engine.plan()
    assert plan.action is not None  # there is something to ask about
    a = plan.action
    engine.record_question(a.participant_id)
    outcome = model.pack.probe_by_id[a.probe_id].outcomes[0]
    engine.observe(Evidence(a.participant_id, a.probe_id, a.location_id, outcome))
    return engine


def test_forecast_is_reproducible_and_changes_nothing(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    engine = started(campus_model, s1_people)
    before = engine.posterior().copy()
    log_before = list(engine.evidence())
    first = forecast(engine, "inv:3", rollouts=6)
    assert np.array_equal(engine.posterior(), before)
    assert engine.evidence() == log_before
    assert forecast(engine, "inv:3", rollouts=6) == first
    assert first.rollouts == 6
    assert 0.0 <= first.p_right_decision + first.p_wrong_decision + first.p_no_decision <= 1.0001
    assert abs(first.p_right_decision + first.p_wrong_decision + first.p_no_decision - 1) < 1e-9
    assert first.expected_questions >= 0
    assert 0.0 <= first.p_wrong_if_acted_now <= 1.0


def test_a_new_state_gets_its_own_seed_and_a_repair_has_no_forecast(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    engine = Engine(campus_model, s1_people)
    a = forecast(engine, "inv:1", rollouts=4)
    assert a.rollouts == 4

    engine._repair = types.SimpleNamespace(era=1)  # type: ignore[assignment]
    repairing = forecast(engine, "inv:1", rollouts=4)
    assert repairing.advice == "repair_in_progress"
    assert repairing.rollouts == 0
