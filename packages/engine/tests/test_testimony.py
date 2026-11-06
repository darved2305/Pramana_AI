"""Disagreement explanations (S2) and presence checks (S7)."""

from __future__ import annotations

import numpy as np
import pytest
from engine_testkit import person

from pramana_contracts import ParticipantSpec
from pramana_engine import CompiledModel, Engine, EngineConfig, Evidence, EvidenceError
from pramana_engine.testimony import explain

# -- S2: two students disagree ------------------------------------------------------------------


def s2_engine(model: CompiledModel) -> Engine:
    return Engine(
        model,
        [
            person("p_aarav", ["student"], "lay", "F2_R205"),
            person("p_neha", ["student"], "lay", "F2_R210"),
            person("p_aarav2", ["student"], "lay", "F2_R205"),
        ],
    )


def test_different_access_points_reconcile_two_students(campus_model: CompiledModel) -> None:
    """Room 205 is also covered by AP 2B; room 210 only by AP 2A. If AP 2A failed, both are
    right, and only Neha's room depends on it."""
    eng = s2_engine(campus_model)
    first = eng.observe(Evidence("p_aarav", "internet_works", "F2_R205", "yes"))
    assert first.disagreements == ()
    r = eng.observe(Evidence("p_neha", "internet_works", "F2_R210", "no"))
    assert r.contradiction == []  # reconcilable, so not a hard contradiction
    (d,) = r.disagreements
    assert (d.earlier.participant_id, d.new.participant_id) == ("p_aarav", "p_neha")
    assert d.reconciling == "AP_2A.dead"
    assert d.only_one_depends == (("new", "AP_2A"),)
    assert 0.0 < d.p_both_right <= 1.0
    assert 0.0 <= d.earlier.p_mistaken <= 1.0
    assert 0.0 <= d.new.p_mistaken <= 1.0


def test_disagreement_numbers_are_posterior_sums(campus_model: CompiledModel) -> None:
    eng = s2_engine(campus_model)
    eng.observe(Evidence("p_aarav", "internet_works", "F2_R205", "yes"))
    (d,) = eng.observe(Evidence("p_neha", "internet_works", "F2_R210", "no")).disagreements
    post = eng.posterior()
    pred = campus_model.predictions
    a = campus_model.site_index[("internet_works", "F2_R205")]
    b = campus_model.site_index[("internet_works", "F2_R210")]
    yes, no = (campus_model.outcomes["internet_works"].index(o) for o in ("yes", "no"))
    known = pred[:, 0] >= 0
    assert d.p_both_right == pytest.approx(post[(pred[:, a] == yes) & (pred[:, b] == no)].sum())
    assert d.earlier.p_mistaken == pytest.approx(post[known & (pred[:, a] != yes)].sum())
    # Every known hypothesis is in exactly one of: both right, earlier wrong only, new wrong
    # only, both wrong. So P(both right) + P(at least one wrong) = P(known).
    either_wrong = post[known & ((pred[:, a] != yes) | (pred[:, b] != no))].sum()
    assert d.p_both_right + either_wrong == pytest.approx(post[known].sum())


def test_same_place_contradiction_has_no_reconciling_cause(campus_model: CompiledModel) -> None:
    eng = Engine(
        campus_model,
        [
            person("p_a", ["student"], "lay", "F3_R304"),
            person("p_b", ["student"], "lay", "F3_R304"),
        ],
    )
    eng.observe(Evidence("p_a", "wifi_status", "F3_R304", "no_network"))
    r = eng.observe(Evidence("p_b", "wifi_status", "F3_R304", "connected"))
    (d,) = r.disagreements
    assert r.contradiction  # also a hard contradiction
    assert d.kind == "one_mistaken"
    assert d.p_both_right == 0.0
    assert d.reconciling is None
    assert d.only_one_depends == ()


def test_a_third_answer_decides_who_was_likelier_mistaken(campus_model: CompiledModel) -> None:
    eng = Engine(
        campus_model,
        [
            person("p_a", ["student"], "lay", "F3_R304"),
            person("p_b", ["student"], "lay", "F3_R304"),
            person("p_c", ["student"], "lay", "F3_R304"),
        ],
    )
    eng.observe(Evidence("p_a", "wifi_status", "F3_R304", "no_network"))
    eng.observe(Evidence("p_b", "wifi_status", "F3_R304", "connected"))
    r = eng.observe(Evidence("p_c", "wifi_status", "F3_R304", "connected"))
    (vs_a,) = [d for d in r.disagreements if d.earlier.participant_id == "p_a"]
    assert vs_a.likelier_mistaken is not None
    assert vs_a.likelier_mistaken.participant_id == "p_a"  # two people saw it connected


@pytest.mark.parametrize(
    ("earlier", "new"),
    [
        (
            ("p_aarav", "internet_works", "F2_R205", "yes"),
            ("p_aarav", "internet_works", "F2_R205", "no"),
        ),
        (
            ("p_aarav", "internet_works", "F2_R205", "yes"),
            ("p_aarav2", "internet_works", "F2_R205", "yes"),
        ),
        (
            ("p_aarav", "internet_works", "F2_R205", "yes"),
            ("p_neha", "wifi_status", "F2_R210", "no_network"),
        ),
    ],
    ids=["same person", "same answer", "different probe"],
)
def test_not_disagreements(
    campus_model: CompiledModel, earlier: tuple[str, ...], new: tuple[str, ...]
) -> None:
    eng = s2_engine(campus_model)
    eng.observe(Evidence(*earlier))
    assert eng.observe(Evidence(*new)).disagreements == ()


def test_explain_is_pure(campus_model: CompiledModel) -> None:
    post = campus_model.prior.copy()
    args = (("x", "internet_works", "F2_R205", "yes"), ("y", "internet_works", "F2_R210", "no"))
    assert explain(campus_model, post, *args) == explain(campus_model, post, *args)
    assert np.array_equal(post, campus_model.prior)


# -- S7: a claim of being somewhere ---------------------------------------------------------------

S7_CLAIM = Evidence("p_mahesh", "switch_leds", "IDF2", "green")


def s7_people(guard_at: str = "GUARD_DESK") -> list[ParticipantSpec]:
    return [
        person("p_neha", ["student"], "lay", "F2_R210"),
        person("p_mahesh", ["guard"], "access", guard_at),
    ]


def s7_engine(model: CompiledModel, guard_at: str = "GUARD_DESK", **cfg: float) -> Engine:
    eng = Engine(model, s7_people(guard_at), EngineConfig(**cfg))  # type: ignore[arg-type]
    eng.observe(Evidence("p_neha", "wifi_status", "F2_R210", "no_network"))
    eng.observe(Evidence("p_neha", "corridor_lights", "F2_R210", "on"))
    return eng


def test_s7_decision_critical_claim_from_a_closet_is_challenged(
    campus_model: CompiledModel,
) -> None:
    eng = s7_engine(campus_model)
    r = eng.observe(S7_CLAIM)
    assert r.decision_critical
    assert eng.presence_challenge(S7_CLAIM, r) == "idf2_switch_label"


def test_pending_check_discounts_the_claim_and_a_pass_restores_it(
    campus_model: CompiledModel,
) -> None:
    trusted = s7_engine(campus_model)
    trusted.observe(S7_CLAIM)
    eng = s7_engine(campus_model)
    eng.observe(S7_CLAIM)
    eng.set_presence("p_mahesh", "IDF2", "pending")
    assert eng.presence("p_mahesh", "IDF2") == "pending"
    assert not np.allclose(eng.posterior(), trusted.posterior())
    eng.set_presence("p_mahesh", "IDF2", "verified")
    assert np.allclose(eng.posterior(), trusted.posterior())


def test_failed_check_keeps_the_discount_and_puts_them_back(campus_model: CompiledModel) -> None:
    eng = s7_engine(campus_model)
    eng.observe(S7_CLAIM)
    assert eng.participants["p_mahesh"].location_id == "IDF2"  # assumed to have gone there
    eng.set_presence("p_mahesh", "IDF2", "pending")
    pending = eng.posterior().copy()
    eng.set_presence("p_mahesh", "IDF2", "failed")
    assert np.allclose(eng.posterior(), pending)
    assert eng.participants["p_mahesh"].location_id == "GUARD_DESK"


def test_discount_is_exactly_the_configured_weight(campus_model: CompiledModel) -> None:
    """A failed check at weight w is the same belief as a claim weighted w without checks."""
    failed = s7_engine(campus_model, presence_unverified_weight=0.2)
    failed.observe(S7_CLAIM)
    failed.set_presence("p_mahesh", "IDF2", "failed")
    zero = s7_engine(campus_model, presence_unverified_weight=0.0)
    zero.observe(S7_CLAIM)
    zero.set_presence("p_mahesh", "IDF2", "failed")
    without = s7_engine(campus_model)
    assert np.allclose(zero.posterior(), without.posterior())  # weight 0: the claim is ignored
    assert not np.allclose(failed.posterior(), without.posterior())


def test_discount_applies_only_to_that_place(campus_model: CompiledModel) -> None:
    eng = s7_engine(campus_model)
    eng.set_presence("p_mahesh", "IDF2", "failed")
    before = eng.posterior().copy()
    eng.observe(Evidence("p_mahesh", "wifi_status", "GUARD_DESK", "connected"))
    reference = s7_engine(campus_model)
    reference.observe(Evidence("p_mahesh", "wifi_status", "GUARD_DESK", "connected"))
    assert np.allclose(eng.posterior(), reference.posterior())
    assert not np.allclose(before, eng.posterior())


@pytest.mark.parametrize(
    ("guard_at", "ev"),
    [
        ("IDF2", S7_CLAIM),  # registered there: nothing to prove
        ("GUARD_DESK", Evidence("p_mahesh", "wifi_status", "GUARD_DESK", "connected")),  # device
        ("GUARD_DESK", Evidence("p_mahesh", "corridor_lights", "GUARD_DESK", "on")),  # open place
    ],
    ids=["registered there", "device answer", "not restricted"],
)
def test_no_challenge_when_presence_is_not_in_question(
    campus_model: CompiledModel, guard_at: str, ev: Evidence
) -> None:
    eng = s7_engine(campus_model, guard_at)
    r = eng.observe(ev)
    assert eng.presence_challenge(ev, r) is None


def test_no_second_challenge_and_none_for_unused_answers(campus_model: CompiledModel) -> None:
    eng = s7_engine(campus_model)
    r = eng.observe(S7_CLAIM)
    eng.set_presence("p_mahesh", "IDF2", "verified")
    assert eng.presence_challenge(S7_CLAIM, r) is None
    eng2 = s7_engine(campus_model)
    unknown = Evidence("p_mahesh", "switch_leds", "IDF2", "unknown")
    assert eng2.presence_challenge(unknown, eng2.observe(unknown)) is None


def test_no_challenge_for_an_answer_that_changes_nothing(campus_model: CompiledModel) -> None:
    eng = s7_engine(campus_model)
    eng.observe(S7_CLAIM)
    eng.set_presence("p_mahesh", "IDF2", "verified")
    again = Evidence("p_mahesh", "nvr_screen", "IDF2", "on")  # consistent with what is known
    r = eng.observe(again)
    assert not r.decision_critical or eng.presence_challenge(again, r) is None


def test_set_presence_validates(campus_model: CompiledModel) -> None:
    eng = s7_engine(campus_model)
    with pytest.raises(EvidenceError):
        eng.set_presence("p_nobody", "IDF2", "pending")
    with pytest.raises(EvidenceError):
        eng.set_presence("p_mahesh", "NOWHERE", "pending")
