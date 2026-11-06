"""Correctness of the observation model and the posterior update."""

from __future__ import annotations

import numpy as np
import pytest
from engine_testkit import person
from hypothesis import given, settings
from hypothesis import strategies as st

from pramana_contracts import Directness, Hedge
from pramana_domain import NO_FAULT, OPEN_WORLD
from pramana_engine import CompiledModel, Engine, Evidence, EvidenceError
from pramana_engine.belief import likelihood_matrix


def toy_engine(model: CompiledModel) -> Engine:
    eng = Engine(
        model,
        [
            person("p_stu", ["student"], "lay", "ROOM"),
            person("p_ele", ["electrician"], "technician", "ROOM"),
        ],
    )
    # Hand-computation tests model a successful proof before panel observations.
    eng.set_presence("p_ele", "PANEL", True)
    return eng


def test_prior_is_normalised_pack_priors(toy_model: CompiledModel) -> None:
    raw = np.array([0.006, 0.004, 0.0015, 0.0005])
    assert [h.id for h in toy_model.hypotheses] == [
        "CB_1.tripped",
        "LAMP.dead",
        NO_FAULT,
        OPEN_WORLD,
    ]
    np.testing.assert_allclose(toy_model.prior, raw / raw.sum(), rtol=0, atol=1e-15)


def test_two_observations_match_hand_computation(toy_model: CompiledModel) -> None:
    eng = toy_engine(toy_model)
    eng.observe(Evidence("p_ele", "lamp", "ROOM", "off"))
    eng.observe(Evidence("p_ele", "breaker", "PANEL", "tripped"))
    # Hand computation. Electrician: visual r = 0.95, panel r = 0.97; two outcomes each.
    # Predictions: lamp off under CB_1.tripped and LAMP.dead, on under NO_FAULT.
    #              breaker tripped only under CB_1.tripped. OPEN_WORLD: 1/2 for every answer.
    unnorm = [
        0.006 * 0.95 * 0.97,  # CB_1.tripped
        0.004 * 0.95 * 0.03,  # LAMP.dead
        0.0015 * 0.05 * 0.03,  # NO_FAULT
        0.0005 * 0.5 * 0.5,  # OPEN_WORLD
    ]
    expected = np.array(unnorm) / sum(unnorm)
    np.testing.assert_allclose(eng.posterior(), expected, rtol=0, atol=1e-12)
    assert eng.snapshot().map_decision == "RESET_BREAKER"


def test_hedged_answer_mixes_toward_uniform(toy_model: CompiledModel) -> None:
    eng = toy_engine(toy_model)
    eng.observe(Evidence("p_stu", "lamp", "ROOM", "off", hedge=Hedge.PROBABLE))
    # lay visual r = 0.85, w = 0.7: M' = 0.7*M + 0.3/2
    on_pred = 0.7 * 0.15 + 0.15
    off_pred = 0.7 * 0.85 + 0.15
    unnorm = [0.006 * off_pred, 0.004 * off_pred, 0.0015 * on_pred, 0.0005 * 0.5]
    np.testing.assert_allclose(eng.posterior(), np.array(unnorm) / sum(unnorm), atol=1e-12)


def test_hearsay_counts_less_than_direct(toy_model: CompiledModel) -> None:
    direct, relayed = toy_engine(toy_model), toy_engine(toy_model)
    direct.observe(Evidence("p_stu", "lamp", "ROOM", "on"))
    relayed.observe(Evidence("p_stu", "lamp", "ROOM", "on", directness=Directness.HEARSAY))
    nf = toy_model.hypothesis_index(NO_FAULT)
    prior_nf = toy_model.prior[nf]
    assert direct.posterior()[nf] > relayed.posterior()[nf] > prior_nf


@pytest.mark.parametrize("hedge", list(Hedge))
def test_likelihood_columns_are_distributions(campus_model: CompiledModel, hedge: Hedge) -> None:
    w = {Hedge.CERTAIN: 1.0, Hedge.PROBABLE: 0.7, Hedge.UNSURE: 0.35}[hedge]
    for site in range(len(campus_model.sites)):
        lik = likelihood_matrix(campus_model, site, 0.9, w)
        np.testing.assert_allclose(lik.sum(axis=0), 1.0, atol=1e-12)
        assert (lik > 0).all()


def test_open_world_is_uniform_and_proper(campus_model: CompiledModel) -> None:
    ow = campus_model.open_world_index
    for site, (probe, _) in enumerate(campus_model.sites):
        lik = likelihood_matrix(campus_model, site, 0.9, 1.0)
        m = len(campus_model.outcomes[probe])
        np.testing.assert_allclose(lik[:, ow], 1.0 / m)


def test_unknown_outcome_and_conclusions_are_not_evidence(toy_model: CompiledModel) -> None:
    eng = toy_engine(toy_model)
    before = eng.posterior()
    r1 = eng.observe(Evidence("p_stu", "lamp", "ROOM", "unknown"))
    r2 = eng.observe(Evidence("p_stu", "lamp", "ROOM", "off", directness=Directness.ASSUMPTION))
    assert not r1.used_as_evidence
    assert not r2.used_as_evidence
    np.testing.assert_array_equal(eng.posterior(), before)


@pytest.mark.parametrize(
    ("ev", "match"),
    [
        (Evidence("p_ghost", "lamp", "ROOM", "on"), "unknown participant"),
        (Evidence("p_stu", "lamp", "PANEL", "on"), "cannot be observed"),
        (Evidence("p_stu", "lamp", "ROOM", "flickering"), "not in"),
        (Evidence("p_stu", "teleport", "ROOM", "on"), "cannot be observed"),
    ],
)
def test_invalid_evidence_is_rejected(toy_model: CompiledModel, ev: Evidence, match: str) -> None:
    eng = toy_engine(toy_model)
    with pytest.raises(EvidenceError, match=match):
        eng.observe(ev)


def test_repeated_answer_supersedes_instead_of_double_counting(toy_model: CompiledModel) -> None:
    once, twice = toy_engine(toy_model), toy_engine(toy_model)
    once.observe(Evidence("p_stu", "lamp", "ROOM", "off"))
    twice.observe(Evidence("p_stu", "lamp", "ROOM", "off"))
    result = twice.observe(Evidence("p_stu", "lamp", "ROOM", "off"))
    assert result.superseded
    np.testing.assert_allclose(twice.posterior(), once.posterior(), atol=1e-15)


def test_changed_answer_replaces_the_earlier_one(toy_model: CompiledModel) -> None:
    eng, ref = toy_engine(toy_model), toy_engine(toy_model)
    eng.observe(Evidence("p_stu", "lamp", "ROOM", "off"))
    eng.observe(Evidence("p_stu", "lamp", "ROOM", "on"))
    ref.observe(Evidence("p_stu", "lamp", "ROOM", "on"))
    np.testing.assert_allclose(eng.posterior(), ref.posterior(), atol=1e-15)


def test_independent_witnesses_do_accumulate(toy_model: CompiledModel) -> None:
    one, two = toy_engine(toy_model), toy_engine(toy_model)
    one.observe(Evidence("p_stu", "lamp", "ROOM", "off"))
    two.observe(Evidence("p_stu", "lamp", "ROOM", "off"))
    two.observe(Evidence("p_ele", "lamp", "ROOM", "off"))
    nf = toy_model.hypothesis_index(NO_FAULT)
    assert two.posterior()[nf] < one.posterior()[nf]


def test_a_wrong_answer_can_lower_the_true_cause(toy_model: CompiledModel) -> None:
    """Posterior of the truth is not monotone: a possible-but-mistaken answer lowers it."""
    eng = toy_engine(toy_model)
    cb = toy_model.hypothesis_index("CB_1.tripped")
    before = eng.posterior()[cb]
    eng.observe(Evidence("p_stu", "lamp", "ROOM", "on"))  # truth is a trip; the student erred
    assert eng.posterior()[cb] < before


def test_contradiction_is_detected(campus_model: CompiledModel) -> None:
    eng = Engine(
        campus_model,
        [
            person("p_a", ["student"], "lay", "F3_R304"),
            person("p_b", ["student"], "lay", "F3_R304"),
        ],
    )
    eng.observe(Evidence("p_a", "wifi_status", "F3_R304", "no_network"))
    result = eng.observe(Evidence("p_b", "wifi_status", "F3_R304", "connected"))
    assert result.contradiction == ["p_a:wifi_status@F3_R304=no_network"]
    consistent = eng.observe(Evidence("p_b", "corridor_lights", "F3_R304", "on"))
    assert consistent.contradiction == []


def test_evidence_no_single_cause_explains_raises_open_world(campus_model: CompiledModel) -> None:
    """Model mismatch: a two-fault world. OPEN_WORLD must absorb it and the plan must abstain."""
    tech = person("p_t", ["it_tech", "electrician"], "technician", "IDF2")
    eng = Engine(campus_model, [tech, person("p_s", ["student"], "lay", "F3_R304")])
    eng.set_presence("p_t", "IDF2", True)
    eng.set_presence("p_t", "F2_CORRIDOR", True)
    # Floor-2/3 lights dead (power) yet the closet's own devices are on and the switch is green.
    eng.observe(Evidence("p_t", "closet_light", "IDF2", "off"))
    eng.observe(Evidence("p_t", "nvr_screen", "IDF2", "on"))
    eng.observe(Evidence("p_t", "switch_leds", "IDF2", "green"))
    eng.observe(Evidence("p_t", "wifi_status", "F2_CORRIDOR", "no_network"))
    eng.observe(Evidence("p_s", "wifi_status", "F3_R304", "no_network"))
    eng.observe(Evidence("p_s", "corridor_lights", "F3_R304", "on"))
    snap = eng.snapshot()
    assert snap.open_world_probability >= 0.25
    plan = eng.plan()
    assert plan.kind.value == "abstain"
    assert plan.rule == "open_world"


@settings(max_examples=60, deadline=None)
@given(
    answers=st.lists(
        st.tuples(st.integers(0, 10_000), st.integers(0, 2), st.sampled_from(list(Hedge))),
        min_size=0,
        max_size=12,
    )
)
def test_posterior_is_always_a_distribution(
    campus_model: CompiledModel, answers: list[tuple[int, int, Hedge]]
) -> None:
    eng = Engine(
        campus_model, [person("p_t", ["guard", "electrician", "it_tech"], "technician", "IDF2")]
    )
    for site_pick, outcome_pick, hedge in answers:
        probe, loc = campus_model.sites[site_pick % len(campus_model.sites)]
        outs = campus_model.outcomes[probe]
        eng.observe(Evidence("p_t", probe, loc, outs[outcome_pick % len(outs)], hedge=hedge))
        p = eng.posterior()
        assert np.all(p >= 0)
        assert abs(p.sum() - 1.0) < 1e-12
        snap = eng.snapshot()
        assert (
            abs(sum(d.probability for d in snap.decisions) + snap.open_world_probability - 1.0)
            < 1e-9
        )


def test_voice_answers_count_slightly_less_than_typed_ones(toy_model: CompiledModel) -> None:
    from pramana_contracts import Modality

    typed, spoken = toy_engine(toy_model), toy_engine(toy_model)
    typed.observe(Evidence("p_ele", "lamp", "ROOM", "off"))
    spoken.observe(Evidence("p_ele", "lamp", "ROOM", "off", modality=Modality.VOICE))
    nf = toy_model.hypothesis_index(NO_FAULT)
    assert typed.posterior()[nf] < spoken.posterior()[nf] < toy_model.prior[nf]
    # Hand check: technician visual r = 0.95, voice weight 0.9 -> M' = 0.9*M + 0.1/2
    off_pred, on_pred = 0.9 * 0.95 + 0.05, 0.9 * 0.05 + 0.05
    unnorm = [0.006 * off_pred, 0.004 * off_pred, 0.0015 * on_pred, 0.0005 * 0.5]
    np.testing.assert_allclose(spoken.posterior(), np.array(unnorm) / sum(unnorm), atol=1e-12)


def test_decision_critical_answers_are_flagged(toy_model: CompiledModel) -> None:
    eng = toy_engine(toy_model)
    lamp = eng.observe(Evidence("p_ele", "lamp", "ROOM", "off"))
    assert not lamp.decision_critical  # "reset the breaker" stays ahead: 0.50 -> 0.58
    breaker = eng.observe(Evidence("p_ele", "breaker", "PANEL", "up"))
    assert breaker.decision_critical  # flips the leading decision to "replace the lamp"
    again = eng.observe(Evidence("p_stu", "lamp", "ROOM", "off"))
    assert not again.decision_critical  # agrees with what is already believed


def test_confirmation_removes_the_voice_discount_or_discards(toy_model: CompiledModel) -> None:
    from pramana_contracts import Modality

    spoken, typed, wrong = toy_engine(toy_model), toy_engine(toy_model), toy_engine(toy_model)
    for eng in (spoken, wrong):
        eng.observe(Evidence("p_ele", "lamp", "ROOM", "off", modality=Modality.VOICE))
    typed.observe(Evidence("p_ele", "lamp", "ROOM", "off"))
    spoken.confirm("p_ele", "lamp", "ROOM", agreed=True)
    np.testing.assert_allclose(spoken.posterior(), typed.posterior(), atol=1e-12)
    wrong.confirm("p_ele", "lamp", "ROOM", agreed=False)
    np.testing.assert_allclose(wrong.posterior(), toy_model.prior, atol=1e-12)
    with pytest.raises(EvidenceError, match="nothing to confirm"):
        wrong.confirm("p_ele", "lamp", "ROOM", agreed=True)
