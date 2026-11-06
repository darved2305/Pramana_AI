from __future__ import annotations

from engine_testkit import person

from pramana_contracts import Directness, Hedge, Modality, PlanKind
from pramana_engine import Engine, EngineConfig, Evidence


def test_restricted_observations_start_at_presence_weight_and_reweight_after_pass(
    campus_model, s1_people
) -> None:
    engine = Engine(campus_model, s1_people)
    evidence = Evidence("p_mahesh", "switch_leds", "IDF2", "off")

    result = engine.observe(evidence)

    assert result.used_as_evidence
    assert result.presence_challenge_needed
    assert engine.evidence_weight(evidence) == 0.2
    assert engine.record_presence_challenge("p_mahesh", "IDF2") is True
    assert engine.record_presence_challenge("p_mahesh", "IDF2") is False

    engine.set_presence("p_mahesh", "IDF2", False)
    assert engine.evidence_weight(evidence) == 0.2
    engine.set_presence("p_mahesh", "IDF2", True)
    assert engine.evidence_weight(evidence) == 1.0


def test_presence_weight_multiplies_existing_hedge_and_voice_weights(campus_model) -> None:
    guard = person("p_guard", ["guard"], "access", "GUARD_DESK")
    engine = Engine(campus_model, [guard])
    evidence = Evidence(
        "p_guard",
        "switch_leds",
        "IDF2",
        "off",
        hedge=Hedge.PROBABLE,
        directness=Directness.HEARSAY,
        modality=Modality.VOICE,
    )

    assert engine.evidence_weight(evidence) == 0.2 * 0.7 * 0.5 * engine.cfg.voice_weight


def test_failed_presence_routes_critical_observation_to_another_person(campus_model) -> None:
    people = [
        person("p_mahesh", ["guard"], "access", "GUARD_DESK"),
        person("p_suresh", ["guard"], "access", "GUARD_DESK"),
    ]
    engine = Engine(campus_model, people)
    evidence = Evidence("p_mahesh", "switch_leds", "IDF2", "off")

    observed = engine.observe(evidence)
    assert observed.presence_challenge_needed
    assert engine.record_presence_challenge("p_mahesh", "IDF2", "switch_leds")
    engine.set_presence("p_mahesh", "IDF2", False, challenge_failed=True)

    plan = engine.plan()

    assert plan.kind == PlanKind.ASK
    assert plan.rule == "presence_fallback"
    assert plan.action is not None
    assert plan.action.participant_id == "p_suresh"
    assert (plan.action.probe_id, plan.action.location_id) == ("switch_leds", "IDF2")


def test_presence_challenge_ablation_keeps_discount_and_removes_challenge_cost(
    campus_model,
) -> None:
    guard = person("p_guard", ["guard"], "access", "GUARD_DESK")
    enabled = Engine(campus_model, [guard])
    disabled = Engine(campus_model, [guard], EngineConfig(presence_challenges_enabled=False))
    enabled_cost = next(cost for action, cost in enabled.menu() if action.probe_id == "switch_leds")
    disabled_cost = next(
        cost for action, cost in disabled.menu() if action.probe_id == "switch_leds"
    )
    assert enabled_cost - disabled_cost == enabled.cfg.presence_challenge_cost_s

    evidence = Evidence("p_guard", "switch_leds", "IDF2", "off")
    assert enabled.observe(evidence).presence_challenge_needed
    assert not disabled.observe(evidence).presence_challenge_needed
    assert disabled.evidence_weight(evidence) == disabled.cfg.unverified_presence_weight


def test_used_presence_challenge_is_not_charged_again(campus_model) -> None:
    guard = person("p_guard", ["guard"], "access", "GUARD_DESK")
    engine = Engine(campus_model, [guard])
    action = next(action for action, _ in engine.menu() if action.probe_id == "switch_leds")
    base_cost = next(
        cost
        for candidate, cost in Engine(
            campus_model,
            [guard],
            EngineConfig(presence_challenges_enabled=False),
        ).menu()
        if candidate == action
    )

    engine.record_presence_challenge("p_guard", "IDF2", "switch_leds")
    engine.set_presence("p_guard", "IDF2", False, challenge_failed=True)
    engine.set_available("p_guard", True)
    retry_cost = next(cost for candidate, cost in engine.menu() if candidate == action)

    assert retry_cost == base_cost


def test_successful_alternate_verification_clears_presence_fallback(campus_model) -> None:
    guard = person("p_mahesh", ["guard"], "access", "GUARD_DESK")
    second_guard = person("p_suresh", ["guard"], "access", "GUARD_DESK")
    engine = Engine(campus_model, [guard, second_guard])
    evidence = Evidence("p_mahesh", "switch_leds", "IDF2", "off")
    engine.observe(evidence)
    engine.record_presence_challenge("p_mahesh", "IDF2", "switch_leds")
    engine.set_presence("p_mahesh", "IDF2", False, challenge_failed=True)
    engine.set_available("p_mahesh", False)
    key = ("switch_leds", "IDF2")
    assert key in engine._presence_recoveries

    engine.record_question("p_suresh", "switch_leds", "IDF2")
    engine.record_presence_challenge("p_suresh", "IDF2", "switch_leds")
    engine.set_presence("p_suresh", "IDF2", True)

    assert key not in engine._presence_recoveries


def test_wifi_context_explanation_comes_from_pack_physics(campus_model) -> None:
    people = [
        person("p_aarav", ["student"], "lay", "F2_R205"),
        person("p_neha", ["student"], "lay", "F2_R210"),
    ]
    engine = Engine(campus_model, people)
    aarav = Evidence("p_aarav", "internet_works", "F2_R205", "yes")
    neha = Evidence("p_neha", "internet_works", "F2_R210", "no")
    engine.observe(aarav)
    engine.observe(neha)

    explanation = engine.explain_reconciliation(aarav, neha)

    families = {family.code: family for family in explanation.families}
    assert families["different_access_points"].posterior_mass > 0
    assert explanation.contexts[0].access_points == ("AP_2B", "AP_2A")
    assert any(
        family.code == "world_changed" and family.posterior_mass == 0 and not family.supported
        for family in explanation.families
    )
    assert explanation.tie_break_action is not None
    assert explanation.tie_break_action.probe_id == "wifi_access_point"
    assert explanation.tie_break_action.participant_id == "p_aarav"


def test_reconciliation_without_different_ap_mass_has_no_ap_tie_break(campus_model) -> None:
    people = [
        person("p_aarav", ["student"], "lay", "F2_R205"),
        person("p_neha", ["student"], "lay", "F2_R205"),
    ]
    engine = Engine(campus_model, people)
    first = Evidence("p_aarav", "internet_works", "F2_R205", "yes")
    second = Evidence("p_neha", "internet_works", "F2_R205", "no")
    engine.observe(first)
    engine.observe(second)

    explanation = engine.explain_reconciliation(first, second)

    families = {family.code: family for family in explanation.families}
    assert families["different_access_points"].posterior_mass == 0.0
    assert explanation.tie_break_action is None
