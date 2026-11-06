"""Correctness of probe selection, value of information and the stopping rule."""

from __future__ import annotations

import itertools
import math
import time

import numpy as np
import pytest
from engine_testkit import person

from pramana_contracts import ParticipantSpec, PlanKind
from pramana_domain import DomainPack, World
from pramana_engine import CompiledModel, Engine, EngineConfig, Evidence
from pramana_engine.belief import likelihood_matrix


def _entropy(xs: list[float]) -> float:
    return -sum(x * math.log2(x) for x in xs if x > 0)


def brute_force_eig(
    model: CompiledModel, p: np.ndarray, site: int, r_any: float | np.ndarray
) -> tuple[float, float]:
    """Mutual information I(H;O) and I(D;O) from their definitions, with plain Python loops.

    ``r_any`` is one reliability, or one per hypothesis (the person's posterior mean).
    """
    rs = [float(x) for x in np.broadcast_to(np.asarray(r_any, dtype=float), (len(p),))]
    probe = model.sites[site][0]
    outs = model.outcomes[probe]
    m = len(outs)
    n_d = len(model.decisions) + 1
    eig_h = eig_d = 0.0
    p_d = [0.0] * n_d
    for hi, ph in enumerate(p):
        p_d[int(model.decision_of[hi])] += ph
    for o in range(m):
        joint = []
        for hi, ph in enumerate(p):
            y = model.predictions[hi, site]
            r = rs[hi]
            lik = 1.0 / m if y < 0 else (r if o == y else (1 - r) / (m - 1))
            joint.append(ph * lik)
        po = sum(joint)
        for hi, j in enumerate(joint):
            if j > 0:
                eig_h += j * math.log2(j / (po * p[hi]))
        jd = [0.0] * n_d
        for hi, j in enumerate(joint):
            jd[int(model.decision_of[hi])] += j
        for di, j in enumerate(jd):
            if j > 0:
                eig_d += j * math.log2(j / (po * p_d[di]))
    return eig_h, eig_d


def s1_engine(
    model: CompiledModel, people: list[ParticipantSpec], config: EngineConfig | None = None
) -> Engine:
    eng = Engine(model, people, config)
    eng.observe(Evidence("p_riya", "internet_works", "F3_R304", "no"))
    return eng


@pytest.mark.parametrize("reliability_model", ["fixed", "beta"])
def test_eig_matches_brute_force(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec], reliability_model: str
) -> None:
    eng = s1_engine(campus_model, s1_people, EngineConfig(reliability_model=reliability_model))  # type: ignore[arg-type]
    plan = eng.plan()
    p = eng.posterior()
    assert plan.candidates
    for cand in plan.candidates:
        a = cand.action
        site = campus_model.site_index[(a.probe_id, a.location_id)]
        skill = eng.participants[a.participant_id].spec.skill
        r: float | np.ndarray = (
            eng.reliability(skill, a.probe_id)
            if reliability_model == "fixed"
            else eng.effective_reliability(a.participant_id, a.probe_id)
        )
        eig_h, eig_d = brute_force_eig(campus_model, p, site, r)
        assert cand.eig_hypothesis_bits == pytest.approx(eig_h, abs=1e-9)
        assert cand.eig_decision_bits == pytest.approx(eig_d, abs=1e-9)
        # Data-processing inequality: the decision is a function of the hypothesis.
        assert -1e-12 <= cand.eig_decision_bits <= cand.eig_hypothesis_bits + 1e-12
        assert (
            cand.eig_decision_bits
            <= _entropy([d.probability for d in eng.snapshot().decisions]) + 1.0
        )


def test_predictive_preserves_the_prior_in_expectation(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    """Martingale property: E_o[P(h | o)] = P(h). Planning cannot manufacture confidence."""
    eng = s1_engine(campus_model, s1_people)
    p = eng.posterior()
    for site in range(len(campus_model.sites)):
        lik = likelihood_matrix(campus_model, site, 0.9, 1.0)
        joint = lik * p
        expected_post = joint.sum(axis=0)  # sum_o P(o) * P(h|o)
        np.testing.assert_allclose(expected_post, p, atol=1e-12)


def brute_force_two_step(eng: Engine) -> dict[tuple[str, str, str], float]:
    """Reference implementation of the two-step adaptive net value, with explicit loops."""
    model, lam = eng.model, eng.cfg.lambda_min_per_s
    actions, _ = eng._enumerate()
    p = eng.posterior()

    def v(u: np.ndarray) -> float:
        return float((model.loss @ u).min())

    out = {}
    for a in actions:
        total = 0.0
        for o in range(a.lik.shape[0]):
            j = a.lik[o] * p
            po = j.sum()
            best = v(j)
            for b in actions:
                if b is a:
                    continue
                cont = sum(v(b.lik[o2] * j) for o2 in range(b.lik.shape[0])) + lam * b.cost_s * po
                best = min(best, cont)
            total += best
        key = (a.participant.spec.id, a.probe_id, a.location_id)
        out[key] = v(p) - lam * a.cost_s - total
    return out


def test_two_step_value_matches_brute_force(
    campus: DomainPack, campus_model: CompiledModel
) -> None:
    people = [
        person("p_riya", ["student"], "lay", "F3_R304"),
        person("p_g", ["guard"], "access", "IDF2"),
    ]
    eng = Engine(campus_model, people)
    eng.observe(Evidence("p_riya", "wifi_status", "F3_R304", "no_network"))
    actions, _ = eng._enumerate()
    fast = eng._two_step_net_value(actions, eng.posterior())
    ref = brute_force_two_step(eng)
    for a, value in zip(actions, fast, strict=True):
        assert value == pytest.approx(
            ref[(a.participant.spec.id, a.probe_id, a.location_id)], abs=1e-9
        )


def test_first_question_goes_to_the_reporter_and_discriminates(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    plan = s1_engine(campus_model, s1_people).plan()
    assert plan.kind == PlanKind.ASK
    assert plan.action is not None
    assert plan.action.participant_id == "p_riya"
    assert plan.action.probe_id == "wifi_status"
    assert "bits about the decision" in plan.reason


def test_cheaper_equivalent_observation_wins(campus_model: CompiledModel) -> None:
    """Two guards can read the same closet indicators; the one already nearby is asked."""
    near = person("p_near", ["guard"], "access", "F2_CORRIDOR")
    far = person("p_far", ["guard"], "access", "GUARD_DESK")
    eng = Engine(
        campus_model, [far, near, person("p_riya", ["student"], "lay", "F3_R304", budget=0)]
    )
    eng.observe(Evidence("p_riya", "wifi_status", "F3_R304", "no_network"))
    eng.observe(Evidence("p_riya", "corridor_lights", "F3_R304", "on"))
    plan = eng.plan()
    assert plan.action is not None
    assert plan.action.participant_id == "p_near"
    by_who = {}
    for c in plan.candidates:
        key = (c.action.probe_id, c.action.location_id)
        by_who.setdefault(key, {})[c.action.participant_id] = c
    for key, d in by_who.items():
        if {"p_near", "p_far"} <= set(d):
            assert d["p_near"].cost_s < d["p_far"].cost_s
            assert d["p_near"].eig_decision_bits == pytest.approx(d["p_far"].eig_decision_bits)
            assert d["p_near"].score > d["p_far"].score, key


def test_permissions_and_access_are_enforced(campus_model: CompiledModel) -> None:
    eng = Engine(campus_model, [person("p_riya", ["student"], "lay", "F3_R304")])
    actions, blocked = eng._enumerate()
    assert all(a.participant.spec.id == "p_riya" for a in actions)
    assert all(a.location_id == "F3_R304" for a in actions)
    assert "needs role guard/it_tech/electrician" in blocked[("nvr_screen", "IDF2")]
    assert "no access to IDF2" in blocked[("nvr_screen", "IDF2")]
    assert "needs role electrician" in blocked[("breaker_c2_7", "DB_C2_PANEL")]


def test_unavailable_or_exhausted_participants_are_not_asked(campus_model: CompiledModel) -> None:
    eng = Engine(
        campus_model,
        [
            person("p_riya", ["student"], "lay", "F3_R304", budget=1),
            person("p_g", ["guard"], "access", "IDF2", available=False),
        ],
    )
    eng.record_question("p_riya")
    actions, blocked = eng._enumerate()
    assert actions == []
    assert any("participant unavailable" in r for r in blocked.values())
    assert any("question budget used" in r for r in blocked.values())


def test_no_feasible_observation_abstains_with_what_would_help(campus_model: CompiledModel) -> None:
    eng = Engine(campus_model, [person("p_riya", ["student"], "lay", "F3_R304", budget=0)])
    eng.observe(Evidence("p_riya", "wifi_status", "F3_R304", "no_network"))
    plan = eng.plan()
    assert plan.kind == PlanKind.ABSTAIN
    assert plan.rule == "no_feasible_action"
    assert plan.infeasible
    assert "Would help" in plan.reason


def test_unidentifiable_with_available_people_abstains(
    campus_model: CompiledModel, campus: DomainPack
) -> None:
    """Scenario S4: only a student without closet access; switch vs closet power is undecidable."""
    world = World(campus, frozenset({("SW_C2", "dead")}))
    eng = Engine(campus_model, [person("p_riya", ["student"], "lay", "F3_R304", budget=6)])
    for _ in range(8):
        plan = eng.plan()
        if plan.kind != PlanKind.ASK:
            break
        assert plan.action is not None
        a = plan.action
        eng.record_question(a.participant_id)
        truth = world.observe(campus.probe_by_id[a.probe_id], a.location_id)
        eng.observe(Evidence(a.participant_id, a.probe_id, a.location_id, truth))
    assert plan.kind == PlanKind.ABSTAIN
    blocked = {(i.probe_id, i.location_id) for i in plan.infeasible}
    assert blocked & {
        ("nvr_screen", "IDF2"),
        ("breaker_c2_7", "DB_C2_PANEL"),
        ("switch_leds", "IDF2"),
        ("ap_light", "F3_CORRIDOR"),
    }


def run_investigation(
    campus: DomainPack, model: CompiledModel, people: list[ParticipantSpec], fault: tuple[str, str]
) -> tuple[list[tuple[str, str, str, str]], str]:
    world = World(campus, frozenset({fault}))
    eng = Engine(model, people)
    eng.observe(
        Evidence(
            "p_riya",
            "internet_works",
            "F3_R304",
            world.observe(campus.probe_by_id["internet_works"], "F3_R304"),
        )
    )
    path = []
    for _ in range(15):
        plan = eng.plan()
        if plan.kind != PlanKind.ASK:
            return path, f"{plan.kind.value}:{plan.decision_class}"
        assert plan.action is not None
        a = plan.action
        eng.record_question(a.participant_id)
        ans = world.observe(campus.probe_by_id[a.probe_id], a.location_id)
        path.append((a.participant_id, a.probe_id, a.location_id, ans))
        if eng.presence_required(a.participant_id, a.location_id):
            # Noise-free world simulations model an honest participant passing the site check.
            eng.set_presence(a.participant_id, a.location_id, True)
        eng.observe(Evidence(a.participant_id, a.probe_id, a.location_id, ans))
    raise AssertionError("did not terminate")


@pytest.mark.parametrize(
    ("fault", "decision"),
    [
        (("CB_C2_7", "tripped"), "DISPATCH_ELECTRICIAN_DB_C2"),
        (("SW_C2", "dead"), "IT_ONSITE_SW_C2"),
        (("DNS", "down"), "IT_FIX_DNS"),
        (("ISP_LINK", "down"), "ESCALATE_ISP"),
        (("DHCP", "down"), "IT_FIX_DHCP"),
        (("FEED_C2", "lost"), "ESCALATE_FACILITIES_POWER"),
    ],
)
def test_noise_free_investigations_reach_the_true_decision(
    campus: DomainPack,
    campus_model: CompiledModel,
    s1_people: list[ParticipantSpec],
    fault: tuple[str, str],
    decision: str,
) -> None:
    path, outcome = run_investigation(campus, campus_model, s1_people, fault)
    assert outcome == f"decide:{decision}", path
    assert len(path) <= 8


def test_different_faults_produce_different_trajectories(
    campus: DomainPack, campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    paths = {
        f: run_investigation(campus, campus_model, s1_people, f)[0]
        for f in [("CB_C2_7", "tripped"), ("SW_C2", "dead"), ("DNS", "down")]
    }
    for (fa, pa), (fb, pb) in itertools.combinations(paths.items(), 2):
        assert pa != pb, (fa, fb)
    # The first question is the same (nothing known yet); the answer changes what comes next.
    assert paths[("CB_C2_7", "tripped")][0][:3] == paths[("DNS", "down")][0][:3]
    assert paths[("CB_C2_7", "tripped")][1][:3] != paths[("DNS", "down")][1][:3]


def test_planning_is_deterministic(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    a = s1_engine(campus_model, s1_people).plan().model_dump_json()
    b = s1_engine(campus_model, list(reversed(s1_people))).plan().model_dump_json()
    assert a == b


def test_confident_belief_decides_without_asking(campus_model: CompiledModel) -> None:
    tech = person("p_t", ["electrician", "guard"], "technician", "DB_C2_PANEL")
    eng = Engine(campus_model, [tech])
    eng.set_presence("p_t", "DB_C2_PANEL", True)
    eng.set_presence("p_t", "IDF2", True)
    for probe, loc, out in [
        ("breaker_c2_7", "DB_C2_PANEL", "tripped"),
        ("nvr_screen", "IDF2", "off"),
        ("closet_light", "IDF2", "on"),
        ("switch_leds", "IDF2", "off"),
    ]:
        eng.observe(Evidence("p_t", probe, loc, out))
    plan = eng.plan()
    assert plan.kind == PlanKind.DECIDE
    assert plan.rule == "confident"
    assert plan.decision_class == "DISPATCH_ELECTRICIAN_DB_C2"
    snap = eng.snapshot()
    # Confidence and expected loss are separate quantities and are both reported.
    assert snap.map_decision_probability >= 0.95
    expected = float((campus_model.loss @ eng.posterior()).min())
    assert snap.expected_loss_now_min == pytest.approx(expected)


def test_plan_latency_budget(campus_model: CompiledModel, s1_people: list[ParticipantSpec]) -> None:
    eng = s1_engine(campus_model, s1_people)
    eng.plan()
    times = []
    for _ in range(15):
        t = time.perf_counter()
        eng.plan()
        times.append(time.perf_counter() - t)
    assert sorted(times)[int(0.9 * len(times))] < 0.25  # NFR target is 100 ms on a server


@pytest.mark.parametrize("top", [1, 8])
def test_chosen_action_is_always_in_the_trace(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec], top: int
) -> None:
    from pramana_engine import EngineConfig

    eng = Engine(campus_model, s1_people, EngineConfig(top_candidates=top))
    for probe, loc, who, out in [
        ("wifi_status", "F3_R304", "p_riya", "no_network"),
        ("corridor_lights", "F3_R304", "p_riya", "on"),
        ("internet_works", "MAINT_ROOM", "p_imran", "yes"),
        ("breaker_c2_7", "DB_C2_PANEL", "p_imran", "up"),
    ]:
        eng.record_question(who)
        eng.observe(Evidence(who, probe, loc, out))
        plan = eng.plan()
        if plan.kind == PlanKind.ASK:
            assert plan.action in [c.action for c in plan.candidates]


def test_abstention_never_suggests_an_observation_already_made(
    campus_model: CompiledModel,
) -> None:
    """Regression (live voice run): the guard had read the CCTV screen, yet the abstention
    said that reading "would help". Only the electrician's breaker check remains useful."""
    eng = Engine(
        campus_model,
        [
            person("p_riya", ["student"], "lay", "F3_R304"),
            person("p_g", ["guard"], "access", "GUARD_DESK"),
        ],
    )
    for who, probe, loc, out in [
        ("p_riya", "wifi_status", "F3_R304", "no_network"),
        ("p_riya", "corridor_lights", "F3_R304", "on"),
        ("p_g", "internet_works", "GUARD_DESK", "yes"),
        ("p_g", "nvr_screen", "IDF2", "on"),
    ]:
        eng.record_question(who)
        eng.observe(Evidence(who, probe, loc, out))
    plan = eng.plan()
    suggested = {(i.probe_id, i.location_id) for i in plan.infeasible}
    assert ("nvr_screen", "IDF2") not in suggested
    if plan.kind == PlanKind.ABSTAIN:
        assert ("breaker_c2_7", "DB_C2_PANEL") in suggested
        assert "breaker_c2_7" in plan.reason
