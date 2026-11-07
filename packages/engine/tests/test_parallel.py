"""Parallel questions: conditional gain, batch selection, withdrawal (docs/adr/0011)."""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest

from pramana_contracts import Directness, ParticipantSpec, PlanKind, ProbeAction
from pramana_domain.physics import predict
from pramana_engine import CompiledModel, Engine, EngineConfig, Evidence, schedule


def _s1(
    model: CompiledModel, people: list[ParticipantSpec], cfg: EngineConfig | None = None
) -> Engine:
    eng = Engine(model, people, cfg)
    eng.observe(Evidence("p_riya", "internet_works", "F3_R304", "no"))
    return eng


def _entropy(xs: list[float]) -> float:
    return -sum(x * math.log2(x) for x in xs if x > 0)


def brute_conditional_gain(eng: Engine, pending: list[ProbeAction], cand: ProbeAction) -> float:
    """I(D; O_cand | O_pending) from its definition, with plain loops and fixed reliability."""
    model = eng.model
    p = eng.posterior()
    acts = [*pending, cand]

    def lik(a: ProbeAction, o: int, h: int) -> float:
        site = model.site_index[(a.probe_id, a.location_id)]
        m = len(model.outcomes[a.probe_id])
        y = model.predictions[h, site]
        r = eng.reliability(eng.participants[a.participant_id].spec.skill, a.probe_id)
        if y < 0:
            return 1.0 / m
        return r if o == y else (1 - r) / (m - 1)

    def cond_entropy(actions: list[ProbeAction]) -> float:
        ranges = [range(len(model.outcomes[a.probe_id])) for a in actions]
        total = 0.0
        for combo in itertools.product(*ranges):
            joint = [
                float(p[h]) * math.prod(lik(a, o, h) for a, o in zip(actions, combo, strict=True))
                for h in range(len(p))
            ]
            w = sum(joint)
            if w <= 0:
                continue
            dm = [0.0] * (len(model.decisions) + 1)
            for h, j in enumerate(joint):
                dm[int(model.decision_of[h])] += j / w
            total += w * _entropy(dm)
        return total

    return cond_entropy(pending) - cond_entropy(acts)


def test_conditional_gain_matches_its_definition(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    eng = _s1(campus_model, s1_people, EngineConfig(reliability_model="fixed"))
    plan = eng.plan()
    assert plan.action is not None
    menu = [a for a, _ in eng.menu() if a.participant_id != plan.action.participant_id][:6]
    for cand in menu:
        got, _ = eng.conditional_gain([plan.action], cand)
        assert got == pytest.approx(brute_conditional_gain(eng, [plan.action], cand), abs=1e-9)


def test_with_nothing_pending_the_gain_is_the_ordinary_eig(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    eng = _s1(campus_model, s1_people)
    for c in eng.plan().candidates:
        gd, gh = eng.conditional_gain([], c.action)
        assert gd == pytest.approx(c.eig_decision_bits, abs=1e-9)
        assert gh == pytest.approx(c.eig_hypothesis_bits, abs=1e-9)


def test_asking_the_same_thing_twice_is_worth_less_the_second_time(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    eng = _s1(campus_model, s1_people)
    a = eng.plan().action
    assert a is not None
    alone, _ = eng.conditional_gain([], a)
    again, _ = eng.conditional_gain([a], a)
    assert 0 <= again < alone


def test_parallel_questions_go_to_other_people_on_the_menu(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    eng = _s1(campus_model, s1_people)
    first = eng.plan().action
    assert first is not None
    picks = eng.parallel_questions([first], 3)
    assert 1 <= len(picks) <= 2
    people = [first.participant_id, *(c.action.participant_id for c in picks)]
    assert len(set(people)) == len(people)
    menu = {(a.participant_id, a.probe_id, a.location_id) for a, _ in eng.menu()}
    for c in picks:
        a = c.action
        assert (a.participant_id, a.probe_id, a.location_id) in menu
        assert c.eig_decision_bits >= eng.cfg.parallel_min_bits
        assert c.net_value_min > 0
    # Each pick's recorded gain is conditional on everything chosen before it.
    chosen = [first]
    for c in picks:
        gd, _ = eng.conditional_gain(chosen, c.action)
        assert c.eig_decision_bits == pytest.approx(gd, abs=1e-9)
        chosen.append(c.action)


def test_the_cap_is_respected(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    eng = _s1(campus_model, s1_people)
    first = eng.plan().action
    assert first is not None
    assert eng.parallel_questions([first], 1) == []
    assert len(eng.parallel_questions([first], 2)) <= 1


def test_no_extra_question_when_it_would_add_too_little(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    eng = _s1(campus_model, s1_people, EngineConfig(parallel_min_bits=10.0))
    first = eng.plan().action
    assert first is not None
    assert eng.parallel_questions([first], 3) == []


def test_parallel_selection_is_deterministic(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    runs = []
    for _ in range(2):
        eng = _s1(campus_model, s1_people)
        first = eng.plan().action
        assert first is not None
        runs.append([c.action for c in eng.parallel_questions([first], 3)])
    assert runs[0] == runs[1]


def test_moot_means_the_answer_barely_informs_the_decision(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    eng = _s1(campus_model, s1_people)
    actions = [a for a, _ in eng.menu()]
    flags = eng.moot(actions)
    for a, f in zip(actions, flags, strict=True):
        assert f == (eng.conditional_gain([], a)[0] < eng.cfg.withdraw_bits)
    assert not all(flags)


def test_unknown_question_in_flight_is_an_error(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    from pramana_engine import EvidenceError

    eng = _s1(campus_model, s1_people)
    bad = ProbeAction(
        participant_id="p_nobody",
        probe_id="wifi_status",
        location_id="F3_R304",
        requires_move=False,
    )
    with pytest.raises(EvidenceError):
        eng.moot([bad])


# -- the scheduling rule -------------------------------------------------------------------------


def test_nothing_in_flight_plans_as_before_plus_extras(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    eng = _s1(campus_model, s1_people)
    plan = eng.plan()
    one = schedule(eng, [], 1)
    assert one.plan == plan
    assert one.ask == []
    assert one.withdraw == []
    three = schedule(eng, [], 3)
    assert three.plan == plan
    assert three.ask
    assert [c.action for c in three.ask] == [
        c.action
        for c in eng.parallel_questions([plan.action], 3)  # type: ignore[list-item]
    ]


def _truthful_s1_run(
    model: CompiledModel, people: list[ParticipantSpec], max_parallel: int
) -> tuple[Engine, list[tuple[str, list[ProbeAction]]], PlanKind]:
    """S1 (breaker CB_C2_7 tripped) with noise-free answers, run by the scheduling rule.

    Answers arrive in the order the questions were asked. Returns the engine, a log of
    (what happened, questions involved) and how it ended.
    """
    truth = predict(model.pack, [("CB_C2_7", "tripped")])
    eng = _s1(model, people)
    inflight: list[ProbeAction] = []
    log: list[tuple[str, list[ProbeAction]]] = []
    for _ in range(30):
        s = schedule(eng, inflight, max_parallel)
        gone = [inflight[i] for i in s.withdraw]
        if gone:
            log.append(("withdraw", gone))
        inflight = [a for i, a in enumerate(inflight) if i not in set(s.withdraw)]
        if s.plan is not None:
            if s.plan.kind != PlanKind.ASK:
                assert not inflight, "concluded with a question that still matters in flight"
                return eng, log, s.plan.kind
            assert s.plan.action is not None
            new = [s.plan.action]
        else:
            new = []
        new += [c.action for c in s.ask]
        for a in new:
            eng.record_question(a.participant_id)
        if new:
            log.append(("ask", new))
        inflight += new
        assert len(inflight) <= max_parallel
        assert len({a.participant_id for a in inflight}) == len(inflight)
        a = inflight.pop(0)
        eng.observe(
            Evidence(
                a.participant_id, a.probe_id, a.location_id, truth[(a.probe_id, a.location_id)]
            )
        )
        log.append(("answer", [a]))
    raise AssertionError("did not conclude")


def test_s1_in_parallel_reaches_the_right_decision(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    eng, log, kind = _truthful_s1_run(campus_model, s1_people, 3)
    assert kind == PlanKind.DECIDE
    assert eng.snapshot().map_decision == "DISPATCH_ELECTRICIAN_DB_C2"
    assert any(len(qs) > 1 for what, qs in log if what == "ask")  # it did ask in parallel


def test_sequential_schedule_is_the_old_planner(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    _, log, kind = _truthful_s1_run(campus_model, s1_people, 1)
    assert kind == PlanKind.DECIDE
    assert all(len(qs) == 1 for what, qs in log if what == "ask")
    assert not any(what == "withdraw" for what, _ in log)


def test_a_confident_decision_withdraws_everything_in_flight(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    truth = predict(campus_model.pack, [("CB_C2_7", "tripped")])
    eng = _s1(campus_model, s1_people)
    inflight = [a for a, _ in eng.menu() if a.participant_id == "p_riya"][:1]
    # Everything Imran can see, read correctly, until the decision is confident.
    for a, _ in eng.menu():
        if a.participant_id != "p_imran":
            continue
        eng.observe(
            Evidence(
                a.participant_id, a.probe_id, a.location_id, truth[(a.probe_id, a.location_id)]
            )
        )
        plan = eng.plan()
        if plan.kind == PlanKind.DECIDE and plan.rule == "confident":
            break
    assert plan.kind == PlanKind.DECIDE
    assert plan.rule == "confident"
    s = schedule(eng, inflight, 3)
    assert s.withdraw == [0]
    assert s.plan == plan
    assert s.ask == []


def test_waits_for_answers_that_still_matter(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    eng = _s1(campus_model, s1_people)
    first = eng.plan().action
    assert first is not None
    eng.record_question(first.participant_id)
    s = schedule(eng, [first], 3)
    assert s.plan is None  # do not conclude or re-ask while the answer is on its way
    assert s.withdraw == []
    assert all(c.action.participant_id != first.participant_id for c in s.ask)


def test_max_parallel_must_be_positive(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    with pytest.raises(ValueError):
        schedule(_s1(campus_model, s1_people), [], 0)


def test_no_parallel_questions_while_verifying_a_repair(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    eng = _s1(campus_model, s1_people)
    eng.apply_intervention("reset_breaker", "CB_C2_7", "p_imran")
    first = eng.plan().action
    assert first is not None
    assert eng.parallel_questions([first], 3) == []
    assert eng.moot([first]) == [False]
    assert np.isclose(eng.posterior().sum(), 1.0)


def _walk_for(eng: Engine, pid: str) -> ProbeAction:
    return next(a for a, _ in eng.menu() if a.participant_id == pid and a.requires_move)


def test_a_walk_withdrawn_midway_leaves_the_person_somewhere_between(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    """Withdrawn while walking, they may be at either place: no phone check is asked of them
    (its answer would describe a place we cannot name), and going anywhere counts as a walk."""
    eng = _s1(campus_model, s1_people)
    home = eng.participants["p_mahesh"].location_id
    before = [a for a, _ in eng.menu() if a.participant_id == "p_mahesh"]
    assert any(a.location_id == home and not a.requires_move for a in before)
    walk = _walk_for(eng, "p_mahesh")
    eng.record_question("p_mahesh")
    eng.question_withdrawn(walk)
    after = {
        (a.probe_id, a.location_id): (a, c) for a, c in eng.menu() if a.participant_id == "p_mahesh"
    }
    probes = eng.model.pack.probe_by_id
    assert after, "they can still be asked to go somewhere"
    assert not [
        k for k in after if probes[k[0]].kind in {"internet_works", "wifi_status", "web_by_ip"}
    ]
    assert all(a.requires_move for a, _ in after.values())
    back = [c for (pr, loc), (_, c) in after.items() if loc == home]
    assert back
    assert min(back) > 0, "going back to where they started is a walk too"


def test_answering_at_a_place_settles_where_they_are(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    """Reporting what is there, first hand, means they went to look."""
    eng = _s1(campus_model, s1_people)
    walk = _walk_for(eng, "p_mahesh")
    eng.record_question("p_mahesh")
    eng.question_withdrawn(walk)
    seen = campus_model.outcomes[walk.probe_id][0]
    eng.observe(Evidence("p_mahesh", walk.probe_id, walk.location_id, seen))
    assert eng.participants["p_mahesh"].location_id == walk.location_id
    assert eng.participants["p_mahesh"].may_be_at == set()
    mine = [a for a, _ in eng.menu() if a.participant_id == "p_mahesh"]
    assert any(a.location_id == walk.location_id and not a.requires_move for a in mine)


@pytest.mark.parametrize(
    ("outcome", "directness"),
    [("unknown", Directness.DIRECT), (None, Directness.HEARSAY), (None, Directness.ASSUMPTION)],
)
def test_an_answer_that_is_not_a_first_hand_look_does_not_place_them_there(
    campus_model: CompiledModel,
    s1_people: list[ParticipantSpec],
    outcome: str | None,
    directness: Directness,
) -> None:
    """ "I could not get there", noise, or "someone told me": they may or may not have gone.
    Planning them as there would skip the walk next time and pin their phone's answers to a
    place they never reached (found by test_adversarial_state against the real simulator)."""
    eng = _s1(campus_model, s1_people)
    home = eng.participants["p_mahesh"].location_id
    walk = _walk_for(eng, "p_mahesh")
    eng.record_question("p_mahesh")
    said = outcome or campus_model.outcomes[walk.probe_id][0]
    eng.observe(Evidence("p_mahesh", walk.probe_id, walk.location_id, said, directness=directness))
    ps = eng.participants["p_mahesh"]
    assert ps.location_id == home
    assert ps.may_be_at == {walk.location_id}
    mine = [a for a, _ in eng.menu() if a.participant_id == "p_mahesh"]
    probes = eng.model.pack.probe_by_id
    assert not [
        a for a in mine if probes[a.probe_id].kind in {"internet_works", "wifi_status", "web_by_ip"}
    ]
    assert all(a.requires_move for a in mine if a.location_id == walk.location_id)


def test_withdrawing_a_question_asked_where_they_stand_changes_nothing(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec]
) -> None:
    eng = _s1(campus_model, s1_people)
    here = next(a for a, _ in eng.menu() if a.participant_id == "p_mahesh" and not a.requires_move)
    menu_before = eng.menu()
    eng.question_withdrawn(here)
    assert eng.menu() == menu_before


def test_the_scheduler_plans_after_telling_the_engine_about_a_withdrawn_walk(
    campus_model: CompiledModel, s1_people: list[ParticipantSpec], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The questions chosen in the same step as a withdrawal already know the person may have
    walked: none of them is a phone check where they started."""
    eng = _s1(campus_model, s1_people)
    walk = _walk_for(eng, "p_mahesh")
    eng.record_question("p_mahesh")
    monkeypatch.setattr(Engine, "moot", lambda self, pending: [True for _ in pending])
    step = schedule(eng, [walk], 3)
    assert step.withdraw == [0]
    assert eng.participants["p_mahesh"].may_be_at == {walk.location_id}
    chosen = [c.action for c in step.ask]
    if step.plan is not None and step.plan.action is not None:
        chosen.append(step.plan.action)
    probes = eng.model.pack.probe_by_id
    for a in chosen:
        if a.participant_id == "p_mahesh":
            assert a.requires_move
            assert probes[a.probe_id].kind not in {"internet_works", "wifi_status", "web_by_ip"}
