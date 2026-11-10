"""Reliability integrated out by quadrature, fault pairs, and properties of the posterior."""

from __future__ import annotations

import json

import numpy as np
import pytest
from engine_testkit import person
from hypothesis import given, settings
from hypothesis import strategies as st

from pramana_contracts import Hedge, ParticipantSpec, PlanKind
from pramana_domain import NO_FAULT, OPEN_WORLD, DomainPack, World
from pramana_engine import CompiledModel, Engine, EngineConfig, Evidence, compile_pack
from pramana_engine.belief import decision_marginal, entropy_bits
from pramana_engine.model import MULTIPLE_FAULTS
from pramana_engine.quadrature import beta_moments, beta_reliability_rule, gauss_jacobi

FIXED = EngineConfig(reliability_model="fixed")

# -- quadrature -------------------------------------------------------------------------------


@pytest.mark.parametrize("mean", [0.6, 0.75, 0.85, 0.92, 0.97])
@pytest.mark.parametrize("nodes", [1, 3, 8])
def test_gauss_jacobi_rule_is_exact_for_beta_moments(mean: float, nodes: int) -> None:
    r, w = (np.asarray(v) for v in beta_reliability_rule(mean, 20.0, nodes))
    mu = (mean - 0.5) / 0.5
    a, b = mu * 20.0, (1 - mu) * 20.0
    x = (r - 0.5) / 0.5
    exact = beta_moments(a, b, 2 * nodes - 1)
    for k in range(2 * nodes):
        assert float(w @ x**k) == pytest.approx(exact[k], abs=1e-13)
    assert np.all((r > 0.5) & (r < 1.0))
    assert float(w @ r) == pytest.approx(mean, abs=1e-15)


def test_gauss_jacobi_rejects_bad_parameters() -> None:
    with pytest.raises(ValueError):
        gauss_jacobi(0, 1.0, 1.0)
    with pytest.raises(ValueError):
        gauss_jacobi(3, -1.0, 1.0)
    with pytest.raises(ValueError):
        beta_reliability_rule(0.5, 20.0, 4)
    with pytest.raises(ValueError):
        EngineConfig(quadrature_nodes=0)


# -- hand computation with an unknown reliability ---------------------------------------------


def _answer_poly(model: CompiledModel, h: int, site: int, outcome: str) -> tuple[float, float]:
    """(slope, intercept) of P(answer | h, r) as a function of r (a certain, direct answer)."""
    probe = model.sites[site][0]
    m = len(model.outcomes[probe])
    y = model.predictions[h, site]
    if y < 0:
        return 0.0, 1.0 / m
    if model.outcomes[probe][y] == outcome:
        return 1.0, 0.0
    return -1.0 / (m - 1), 1.0 / (m - 1)


def test_same_person_answers_match_the_exact_beta_integral(campus_model: CompiledModel) -> None:
    """Two answers by one person in one probe class: E[(a1 r + b1)(a2 r + b2)] per hypothesis.

    With r = 0.5 + 0.5 x and x ~ Beta(a, b): E[r] and E[r^2] from the closed-form moments.
    """
    riya = person("p_riya", ["student"], "lay", "F3_R304")
    eng = Engine(campus_model, [riya])
    answers = [("internet_works", "no"), ("wifi_status", "no_network")]
    for probe, out in answers:
        eng.observe(Evidence("p_riya", probe, "F3_R304", out))
    mean, kappa = 0.92, 20.0  # lay, device
    mu = (mean - 0.5) / 0.5
    m1, m2 = beta_moments(mu * kappa, (1 - mu) * kappa, 2)[1:]
    e_r = 0.5 + 0.5 * m1
    e_r2 = 0.25 + 0.5 * m1 + 0.25 * m2
    unnorm = []
    for h in range(len(campus_model.hypotheses)):
        (a1, b1), (a2, b2) = (
            _answer_poly(campus_model, h, campus_model.site_index[(p, "F3_R304")], o)
            for p, o in answers
        )
        lik = a1 * a2 * e_r2 + (a1 * b2 + a2 * b1) * e_r + b1 * b2
        unnorm.append(campus_model.prior[h] * lik)
    expected = np.asarray(unnorm) / sum(unnorm)
    np.testing.assert_allclose(eng.posterior(), expected, rtol=0, atol=1e-12)


def test_fixed_model_is_the_product_of_answer_likelihoods(campus_model: CompiledModel) -> None:
    eng = Engine(campus_model, [person("p_riya", ["student"], "lay", "F3_R304")], FIXED)
    answers = [("internet_works", "no"), ("wifi_status", "no_network")]
    for probe, out in answers:
        eng.observe(Evidence("p_riya", probe, "F3_R304", out))
    unnorm = []
    for h in range(len(campus_model.hypotheses)):
        lik = 1.0
        for p, o in answers:
            a, b = _answer_poly(campus_model, h, campus_model.site_index[(p, "F3_R304")], o)
            lik *= a * 0.92 + b
        unnorm.append(campus_model.prior[h] * lik)
    np.testing.assert_allclose(eng.posterior(), np.asarray(unnorm) / sum(unnorm), atol=1e-12)


def test_one_answer_per_person_and_class_is_the_same_in_both_models(
    toy_model: CompiledModel,
) -> None:
    """The predictive of a first answer is the likelihood at the mean, exactly."""
    people = [
        person("p_stu", ["student"], "lay", "ROOM"),
        person("p_ele", ["electrician"], "technician", "ROOM"),
    ]
    beta, fixed = Engine(toy_model, people), Engine(toy_model, people, FIXED)
    for eng in (beta, fixed):
        eng.observe(Evidence("p_ele", "lamp", "ROOM", "off"))
        eng.observe(Evidence("p_ele", "breaker", "PANEL", "tripped"))
        eng.observe(Evidence("p_stu", "lamp", "ROOM", "off", hedge=Hedge.PROBABLE))
    np.testing.assert_allclose(beta.posterior(), fixed.posterior(), atol=1e-13)


def test_one_persons_repeated_agreement_counts_less_than_two_witnesses(
    campus_model: CompiledModel,
) -> None:
    """Answers that share an unknown reliability are correlated: a person who might be
    unreliable cannot multiply their own evidence. Independent witnesses can."""
    answers = [("internet_works", "no"), ("wifi_status", "no_network"), ("web_by_ip", "no")]

    def run(same_person: bool, cfg: EngineConfig | None = None) -> float:
        people = [person(f"p_{i}", ["student"], "lay", "F3_R304") for i in range(3)]
        eng = Engine(campus_model, people, cfg)
        for i, (probe, out) in enumerate(answers):
            eng.observe(Evidence("p_0" if same_person else f"p_{i}", probe, "F3_R304", out))
        return float(eng.posterior()[campus_model.hypothesis_index(NO_FAULT)])

    assert run(same_person=True) > run(same_person=False)
    assert run(True, FIXED) == pytest.approx(run(False, FIXED), abs=1e-15)


def test_effective_reliability_learns_from_agreement(campus_model: CompiledModel) -> None:
    eng = Engine(campus_model, [person("p_riya", ["student"], "lay", "F3_R304")])
    prior = eng.effective_reliability("p_riya", "wifi_status")
    np.testing.assert_allclose(prior, 0.92, atol=1e-15)
    eng.observe(Evidence("p_riya", "internet_works", "F3_R304", "no"))
    after = eng.effective_reliability("p_riya", "wifi_status")
    nf = campus_model.hypothesis_index(NO_FAULT)
    sw = campus_model.hypothesis_index("SW_C2.dead")
    # Under NO_FAULT her "no" was a mistake, so she looks less reliable; under SW_C2 it fit.
    assert after[nf] < 0.92 < after[sw]
    # Another probe class has its own reliability.
    np.testing.assert_allclose(eng.effective_reliability("p_riya", "corridor_lights"), 0.85)


# -- properties of the posterior (Hypothesis) --------------------------------------------------

ANSWER = st.tuples(
    st.integers(0, 3),  # who
    st.integers(0, 10_000),  # site
    st.integers(0, 2),  # outcome
    st.sampled_from(list(Hedge)),
)


def _people() -> list[ParticipantSpec]:
    return [
        person("p_0", ["guard", "electrician", "it_tech"], "technician", "IDF2"),
        person("p_1", ["guard"], "access", "IDF2"),
        person("p_2", ["student"], "lay", "F3_R304"),
        person("p_3", ["electrician"], "technician", "DB_C2_PANEL"),
    ]


def _evidence(model: CompiledModel, picks: list[tuple[int, int, int, Hedge]]) -> list[Evidence]:
    out: dict[tuple[str, str, str], Evidence] = {}
    for who, s, o, hedge in picks:
        probe, loc = model.sites[s % len(model.sites)]
        outs = model.outcomes[probe]
        ev = Evidence(f"p_{who}", probe, loc, outs[o % len(outs)], hedge=hedge)
        out[(ev.participant_id, probe, loc)] = ev  # one answer per person and site
    return list(out.values())


@settings(max_examples=40, deadline=None)
@given(picks=st.lists(ANSWER, min_size=1, max_size=10), seed=st.integers(0, 2**31))
def test_posterior_is_invariant_to_the_order_of_evidence(
    campus_model: CompiledModel, picks: list[tuple[int, int, int, Hedge]], seed: int
) -> None:
    evs = _evidence(campus_model, picks)
    shuffled = list(evs)
    np.random.default_rng(seed).shuffle(shuffled)
    a, b = Engine(campus_model, _people()), Engine(campus_model, _people())
    for ev in evs:
        a.observe(ev)
    for ev in shuffled:
        b.observe(ev)
    np.testing.assert_allclose(a.posterior(), b.posterior(), rtol=0, atol=1e-12)
    pa = a.posterior()
    assert np.all(pa >= 0)
    assert abs(pa.sum() - 1.0) < 1e-12


@settings(max_examples=40, deadline=None)
@given(picks=st.lists(ANSWER, min_size=0, max_size=8), new=ANSWER)
def test_evidence_never_lowers_the_odds_of_a_cause_it_fits(
    campus_model: CompiledModel,
    picks: list[tuple[int, int, int, Hedge]],
    new: tuple[int, int, int, Hedge],
) -> None:
    """Monotonicity: an answer predicted by h and not by h' never lowers P(h) / P(h')."""
    eng = Engine(campus_model, _people())
    for ev in _evidence(campus_model, picks):
        eng.observe(ev)
    (ev,) = _evidence(campus_model, [new])
    eng._pop_current((ev.participant_id, ev.probe_id, ev.location_id))
    before = eng.posterior()
    eng.observe(ev)
    after = eng.posterior()
    site = campus_model.site_index[(ev.probe_id, ev.location_id)]
    o = campus_model.outcomes[ev.probe_id].index(ev.outcome)
    pred = campus_model.predictions[:, site]
    fits, misses = np.nonzero(pred == o)[0], np.nonzero((pred != o) & (pred >= 0))[0]
    for h in fits[:6]:
        for g in misses[:6]:
            if min(before[h], before[g], after[h], after[g]) < 1e-250:
                continue
            assert np.log(after[h] / after[g]) >= np.log(before[h] / before[g]) - 1e-9


@settings(max_examples=25, deadline=None)
@given(picks=st.lists(ANSWER, min_size=0, max_size=6))
def test_information_gains_are_bounded(
    campus_model: CompiledModel, picks: list[tuple[int, int, int, Hedge]]
) -> None:
    """EIG_D >= 0, EIG_D <= EIG_H (data processing) and EIG_D <= H(D)."""
    eng = Engine(campus_model, _people())
    for ev in _evidence(campus_model, picks):
        eng.observe(ev)
    p = eng.posterior()
    h_d = entropy_bits(decision_marginal(campus_model, p))
    actions, _ = eng._enumerate()
    for a in actions:
        c = eng._score(a, p)
        assert -1e-12 <= c.eig_decision_bits <= c.eig_hypothesis_bits + 1e-9
        assert c.eig_decision_bits <= h_d + 1e-9


# -- fault pairs -------------------------------------------------------------------------------


def test_pairs_are_enumerated_only_when_identifiable(campus_model: CompiledModel) -> None:
    ids = {h.id for h in campus_model.hypotheses}
    assert "CB_C2_7.tripped+ISP_LINK.down" in ids
    # SW_C2 loses power when CB_C2_7 trips: the pair predicts exactly the single fault.
    assert "CB_C2_7.tripped+SW_C2.dead" not in ids
    assert "AP_3A.dead+CB_C2_7.tripped" not in ids
    rows = {tuple(r) for r in campus_model.predictions[:-1]}
    singles = [h for h in campus_model.hypotheses if h.faults is not None and len(h.faults) == 1]
    pairs = [h for h in campus_model.hypotheses if h.faults is not None and len(h.faults) == 2]
    assert pairs
    assert len(rows) >= len(singles)
    for h in pairs:
        i = campus_model.hypothesis_index(h.id)
        for f in h.faults or ():
            j = campus_model.fault_index[frozenset({f})]
            assert not np.array_equal(campus_model.predictions[i], campus_model.predictions[j])
    assert campus_model.hypotheses[-2].id == NO_FAULT
    assert campus_model.hypotheses[-1].id == OPEN_WORLD


def test_pair_prior_decision_and_loss(campus: DomainPack, campus_model: CompiledModel) -> None:
    m = campus_model
    raw = {f"{c}.{mode}": fm.prior for c, mode, fm in campus.fault_hypotheses()}
    names = ("CB_C2_7.tripped+ISP_LINK.down", "CB_C2_7.tripped", "ISP_LINK.down")
    i, a, b = (m.hypothesis_index(x) for x in names)
    assert m.prior[i] / m.prior[a] == pytest.approx(raw["ISP_LINK.down"], rel=1e-12)
    assert m.prior[i] / m.prior[b] == pytest.approx(raw["CB_C2_7.tripped"], rel=1e-12)
    assert m.hypotheses[i].decision_class == MULTIPLE_FAULTS
    same = m.hypothesis_index("CB_C2_5.tripped+CB_C2_7.tripped")
    assert m.hypotheses[same].decision_class == "DISPATCH_ELECTRICIAN_DB_C2"
    d = {x: k for k, x in enumerate(m.decisions)}
    assert m.loss[d[MULTIPLE_FAULTS], i] == 0.0
    assert m.loss[d["DISPATCH_ELECTRICIAN_DB_C2"], i] == 12.5  # half the problem fixed
    assert m.loss[d["ESCALATE_ISP"], i] == 30.0
    assert m.loss[d["IT_FIX_DNS"], i] == 25.0
    assert m.loss[d[MULTIPLE_FAULTS], a] == 25.0  # never a cheap hedge
    assert m.loss[d["DISPATCH_ELECTRICIAN_DB_C2"], same] == 0.0


def test_without_pairs_the_model_is_the_single_fault_model(campus: DomainPack) -> None:
    m = compile_pack(campus, pairs=False)
    assert all(h.faults is None or len(h.faults) <= 1 for h in m.hypotheses)
    assert MULTIPLE_FAULTS not in m.decisions


ANALYST = [
    person("p_riya", ["student"], "lay", "F3_R304"),
    person("p_mahesh", ["guard"], "access", "GUARD_DESK"),
    person("p_imran", ["electrician"], "technician", "MAINT_ROOM"),
    person("p_ravi", ["it_tech"], "technician", "IDF1"),
]


def _investigate(
    campus: DomainPack, eng: Engine, world: World, steps: int = 14
) -> tuple[int, PlanKind]:
    n = 0
    for _ in range(steps):
        plan = eng.plan()
        if plan.kind != PlanKind.ASK:
            return n, plan.kind
        a = plan.action
        assert a is not None
        eng.record_question(a.participant_id)
        out = world.observe(campus.probe_by_id[a.probe_id], a.location_id)
        eng.observe(Evidence(a.participant_id, a.probe_id, a.location_id, out))
        n += 1
    return n, eng.plan().kind


def test_a_two_fault_world_is_diagnosed_as_two_faults(
    campus: DomainPack, campus_model: CompiledModel
) -> None:
    faults = {("CB_C2_7", "tripped"), ("ISP_LINK", "down")}
    world = World(campus, frozenset(faults))
    eng = Engine(campus_model, ANALYST)
    eng.observe(Evidence("p_riya", "internet_works", "F3_R304", "no"))
    _, kind = _investigate(campus, eng, world)
    plan = eng.plan()
    assert kind == PlanKind.DECIDE
    assert plan.decision_class == MULTIPLE_FAULTS
    assert eng.snapshot().hypotheses[0].id == "CB_C2_7.tripped+ISP_LINK.down"
    # The single-fault model can only call it an unknown cause or a wrong single fault.
    single = Engine(compile_pack(campus, pairs=False), ANALYST)
    single.observe(Evidence("p_riya", "internet_works", "F3_R304", "no"))
    _investigate(campus, single, world)
    assert single.plan().decision_class != MULTIPLE_FAULTS


def test_answers_only_a_pair_explains_are_flagged_not_contradictory(
    campus_model: CompiledModel, campus: DomainPack
) -> None:
    tech = person("p_t", ["it_tech", "guard"], "technician", "IDF1")
    eng = Engine(campus_model, [tech])
    single = Engine(compile_pack(campus, pairs=False), [tech])
    world = World(campus, frozenset({("CB_C2_7", "tripped"), ("ISP_LINK", "down")}))
    for probe, loc in [("wan_led", "IDF1"), ("switch_leds", "IDF2"), ("nvr_screen", "IDF2")]:
        out = world.observe(campus.probe_by_id[probe], loc)
        r = eng.observe(Evidence("p_t", probe, loc, out))
        r1 = single.observe(Evidence("p_t", probe, loc, out))
    assert r.multiple_faults_suspected
    assert r.contradiction == []
    assert r1.contradiction  # no single fault reconciles a red WAN light with a dark closet


def test_repairing_one_fault_of_a_pair_reopens_on_the_other(
    campus: DomainPack, campus_model: CompiledModel
) -> None:
    faults = {("CB_C2_7", "tripped"), ("ISP_LINK", "down")}
    eng = Engine(campus_model, ANALYST)
    eng.observe(Evidence("p_riya", "internet_works", "F3_R304", "no"))
    _investigate(campus, eng, World(campus, frozenset(faults)))
    eng.apply_intervention("reset_breaker", "CB_C2_7", "p_imran")
    assert eng.snapshot().repair is not None
    after = World(campus, frozenset({("ISP_LINK", "down")}))  # the reset held; the ISP is down
    _investigate(campus, eng, after, steps=8)
    assert eng.plan().kind == PlanKind.NOT_VERIFIED
    eng.reopen()
    snap = eng.snapshot()
    assert snap.repair is None
    assert snap.hypotheses[0].id == "ISP_LINK.down"  # the remaining fault, in today's world
    _investigate(campus, eng, after, steps=8)
    plan = eng.plan()
    assert plan.kind == PlanKind.DECIDE
    assert plan.decision_class == "ESCALATE_ISP"


# -- determinism ---------------------------------------------------------------------------------


def test_replaying_the_same_evidence_reproduces_the_snapshot_byte_for_byte(
    campus: DomainPack, campus_model: CompiledModel
) -> None:
    def run() -> str:
        eng = Engine(campus_model, ANALYST)
        eng.observe(Evidence("p_riya", "internet_works", "F3_R304", "no"))
        _investigate(campus, eng, World(campus, frozenset({("SW_C2", "dead")})))
        return json.dumps(
            [eng.snapshot().model_dump(mode="json"), eng.plan().model_dump(mode="json")],
            sort_keys=True,
        )

    assert run() == run()


# -- the acceptance scenario -----------------------------------------------------------------------


def test_s1_reaches_the_electrician_dispatch_in_at_most_six_questions(
    campus: DomainPack, campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    """M1: breaker C2-7 tripped; Riya reported "Floor 3 pe WiFi nahi chal raha" (intake maps it
    to internet_works = no in room 304); everyone answers truthfully."""
    world = World(campus, frozenset({("CB_C2_7", "tripped")}))
    eng = Engine(campus_model, s1_people)
    eng.observe(Evidence("p_riya", "internet_works", "F3_R304", "no"))
    asked, kind = _investigate(campus, eng, world, steps=6)
    plan = eng.plan()
    assert kind == PlanKind.DECIDE, plan.reason
    assert plan.decision_class == "DISPATCH_ELECTRICIAN_DB_C2"
    assert plan.decision_probability >= 0.95
    assert asked <= 6


@pytest.mark.parametrize("mean", [0.5005, 0.75, 0.9995])
@pytest.mark.parametrize("concentration", [0.05, 0.999, 1 - 1e-9, 1.0, 1 + 1e-9, 1.001, 1e4])
def test_beta_rule_extreme_shapes(mean: float, concentration: float) -> None:
    nodes = 8
    r, w = (np.asarray(v) for v in beta_reliability_rule(mean, concentration, nodes))
    x = (r - 0.5) / 0.5
    a = (2 * mean - 1) * concentration
    b = concentration - a
    expected = 1.0
    assert np.all(np.isfinite(r))
    assert np.all(w > 0)
    assert w.sum() == pytest.approx(1.0, abs=1e-14)
    for degree in range(2 * nodes):
        if degree:
            expected *= (a + degree - 1) / (a + b + degree - 1)
        assert w @ x**degree == pytest.approx(expected, abs=2e-12)


def test_concentration_one_investigation(campus: DomainPack, campus_model: CompiledModel) -> None:
    eng = Engine(campus_model, ANALYST, EngineConfig(reliability_concentration=1))
    eng.observe(Evidence("p_riya", "internet_works", "F3_R304", "no"))
    _, kind = _investigate(campus, eng, World(campus, frozenset({("SW_C2", "dead")})))
    assert np.isfinite(eng.posterior()).all()
    assert eng.posterior().sum() == pytest.approx(1)
    assert kind != PlanKind.ASK


@pytest.mark.parametrize("pattern", ["unknown", "one_person", "several_people"])
@pytest.mark.parametrize("reliability", [0.500001, 0.999999])
def test_long_contradictory_history_stays_finite(
    toy_model: CompiledModel, pattern: str, reliability: float
) -> None:
    people = [person(f"p_{i}", ["student"], "lay", "ROOM") for i in range(3)]
    cfg = EngineConfig(reliability={key: reliability for key in EngineConfig().reliability})
    eng = Engine(toy_model, people, cfg)
    prior = eng.posterior().copy()
    for i in range(510):
        participant = f"p_{i % 3}" if pattern == "several_people" else "p_0"
        outcome = "unknown" if pattern == "unknown" else ("on" if i % 2 else "off")
        eng.observe(Evidence(participant, "lamp", "ROOM", outcome))
    posterior = eng.posterior()
    assert np.isfinite(posterior).all()
    assert np.all(posterior >= 0)
    assert posterior.sum() == pytest.approx(1.0)
    if pattern == "unknown":
        np.testing.assert_array_equal(posterior, prior)
    assert eng.plan() is not None


def test_replay_is_identical_across_hash_seeds() -> None:
    import os
    import subprocess
    import sys

    script = r"""
import json
from pramana_contracts import ParticipantSpec
from pramana_domain import load_pack
from pramana_engine import Engine, Evidence, compile_pack
p = ParticipantSpec.model_validate({"id": "p", "display_name": "P", "roles": ["student"],
    "skill": "lay", "location_id": "F3_R304", "languages": {"stt_candidates": ["en-IN"]}})
e = Engine(compile_pack(load_pack("campus_block_c")), [p])
for probe, answer in [("internet_works", "no"), ("wifi_status", "no_network")]:
    e.observe(Evidence("p", probe, "F3_R304", answer))
print(json.dumps([e.posterior().tolist(), e.plan().model_dump(mode="json")], sort_keys=True))
"""
    outputs = []
    for seed in ("1", "83417"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        outputs.append(subprocess.check_output([sys.executable, "-c", script], env=env))
    assert outputs[0] == outputs[1]
