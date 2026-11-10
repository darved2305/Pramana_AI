"""Benchmark harness tests. LLM calls are mocked at the HTTP layer (no network, no quota)."""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pytest

from pramana_core.llm import LlmClient, LlmError, ProviderLimits, _duration_s
from pramana_domain import DomainPack, load_pack
from pramana_engine import CompiledModel, EngineConfig, compile_pack
from pramana_eval.llm_policy import LlmPolicy, render_site
from pramana_eval.policies import Checklist, Conclusion, Ours, RandomFeasible, greedy_entropy
from pramana_eval.runner import paired_difference, run_episode, summarize
from pramana_eval.scenarios import Answers, generate


def test_report_discloses_completed_and_excluded_episodes_per_policy() -> None:
    from pramana_eval.__main__ import render

    report = render(
        {
            "git_sha": "test",
            "seeds": [10000, 10099],
            "scenario_mix": {},
            "policies": {"B_llm": {**summarize([]), "n": 22, "failed_runs": 78}},
            "paired_vs_E": {},
        }
    )
    assert "Completed episodes" in report
    assert "Excluded failed runs" in report
    assert "| B_llm | 22 | 78 |" in report
    table = report.splitlines()
    header_index = next(i for i, line in enumerate(table) if line.startswith("| Policy |"))
    assert table[header_index].count("|") == table[header_index + 1].count("|")


@pytest.fixture(scope="module")
def pack() -> DomainPack:
    return load_pack("campus_block_c")


@pytest.fixture(scope="module")
def model(pack: DomainPack) -> CompiledModel:
    return compile_pack(pack)


def test_scenarios_are_reproducible_from_the_seed(pack: DomainPack, model: CompiledModel) -> None:
    assert generate(pack, model, 123) == generate(pack, model, 123)
    kinds = Counter(generate(pack, model, s).kind for s in range(400))
    assert set(kinds) == {"single", "pair", "no_fault", "access_limited"}
    assert kinds["single"] > kinds["pair"] > kinds["no_fault"]


def test_access_limited_scenarios_have_no_staff(pack: DomainPack, model: CompiledModel) -> None:
    for s in range(200):
        sc = generate(pack, model, s)
        if sc.kind == "access_limited":
            assert all(p.spec.skill.value == "lay" for p in sc.people)


def test_answers_use_common_random_numbers(pack: DomainPack, model: CompiledModel) -> None:
    sc = generate(pack, model, 7)
    a, b = Answers(pack, sc), Answers(pack, sc)
    who = sc.people[0].spec
    first = a.ask(who.id, "wifi_status", who.location_id)
    assert first == b.ask(who.id, "wifi_status", who.location_id)  # same question, same answer
    a.ask(who.id, "wifi_status", who.location_id)  # asking again draws a fresh answer
    assert a._asked[(who.id, "wifi_status", who.location_id)] == 2


def test_false_presence_adversary_is_seeded_and_reports_wrong_remote_observations(
    pack: DomainPack, model: CompiledModel
) -> None:
    scenario = generate(pack, model, 20_000, false_presence_rate=1.0)
    assert scenario.presence_adversary_id is not None
    adversary = next(p for p in scenario.people if p.spec.id == scenario.presence_adversary_id)
    assert adversary.false_presence_p == 1.0
    answers = Answers(pack, scenario)
    evidence = answers.ask(scenario.presence_adversary_id, "switch_leds", "IDF2")
    truth = answers.world.observe(pack.probe_by_id["switch_leds"], "IDF2")
    assert answers.last_false_presence(scenario.presence_adversary_id, "switch_leds", "IDF2")
    assert evidence.outcome != truth


def test_presence_check_ablation_runs_through_the_main_engine_api(
    pack: DomainPack, model: CompiledModel
) -> None:
    for seed in range(20_000, 20_030):
        scenario = generate(pack, model, seed, false_presence_rate=1.0)
        if scenario.presence_adversary_id is None:
            continue
        enabled = run_episode(pack, model, scenario, Ours(), presence_checks=True)
        if not enabled.presence_challenges:
            continue
        disabled = run_episode(pack, model, scenario, Ours(), presence_checks=False)
        assert disabled.presence_challenges == 0
        return
    pytest.fail("the adversarial scenarios did not cause the engine to request a challenge")


def test_participants_err_at_their_own_rate(pack: DomainPack, model: CompiledModel) -> None:
    wrong = total = 0
    for s in range(300):
        sc = generate(pack, model, s)
        ans = Answers(pack, sc)
        p = sc.people[0]
        ev = (
            ans.ask(p.spec.id, "corridor_lights", p.spec.location_id)
            if pack.probe_by_id["corridor_lights"].binding_at(p.spec.location_id)
            else None
        )
        if ev is None:
            continue
        truth = ans.world.observe(pack.probe_by_id["corridor_lights"], p.spec.location_id)
        wrong += ev.outcome != truth
        total += 1
    # Lay visual reliability ~ Beta(8, 3): mean 0.73, so roughly a quarter of answers are wrong.
    assert 0.15 < wrong / total < 0.40


@pytest.mark.parametrize("policy", [Ours(), Checklist(), RandomFeasible(), greedy_entropy()])
def test_policies_terminate_and_are_deterministic(
    pack: DomainPack, model: CompiledModel, policy: Any
) -> None:
    sc = generate(pack, model, 11)
    a = run_episode(pack, model, sc, policy)
    b = run_episode(pack, model, sc, policy)
    assert a == b
    assert not a.hit_step_limit


def test_summary_and_paired_difference(pack: DomainPack, model: CompiledModel) -> None:
    scs = [generate(pack, model, s) for s in range(20)]
    e = [run_episode(pack, model, sc, Ours()) for sc in scs]
    a = [run_episode(pack, model, sc, Checklist()) for sc in scs]
    m = summarize(e)
    assert m["n"] == 20
    assert 0 <= m["success_rate"] <= 1
    d = paired_difference(e, a, "probes", resamples=500)
    assert d["ci95_low"] <= d["mean"] <= d["ci95_high"]
    assert d["n"] == 20


def test_duration_parsing() -> None:
    assert _duration_s("1m26.4s") == pytest.approx(86.4)
    assert _duration_s("4.229s") == pytest.approx(4.229)
    assert _duration_s("750ms") == pytest.approx(0.75)


def _reply(content: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        json={
            "choices": [{"message": {"content": json.dumps(content)}}],
            "usage": {"total_tokens": 300},
        },
    )


def client(tmp_path: Path, handler: Any, **limits: Any) -> LlmClient:
    lim = ProviderLimits(
        **{"requests_per_min": 100, "tokens_per_min": 10**6, "requests_per_day": 100, **limits}
    )
    return LlmClient(
        "groq", cache_dir=tmp_path, api_key="k", limits=lim, transport=httpx.MockTransport(handler)
    )


def test_cache_means_never_paying_twice(tmp_path: Path) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _reply({"x": 1})

    c = client(tmp_path, handler)
    msgs = [{"role": "user", "content": "hi"}]
    first = c.complete_json(msgs, {"type": "object"})
    second = c.complete_json(msgs, {"type": "object"})
    assert (first.data, second.data, calls) == ({"x": 1}, {"x": 1}, 1)
    assert second.cached


def test_overload_is_retried_on_the_same_model(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr("time.sleep", lambda _s: None)
    replies = iter([httpx.Response(503, text="high demand"), _reply({"ok": True})])
    seen_models: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen_models.append(json.loads(req.content)["model"])
        return next(replies)

    out = client(tmp_path, handler).complete_json([{"role": "user", "content": "q"}], {})
    assert out.data == {"ok": True}
    assert len(set(seen_models)) == 1


def test_daily_budget_is_enforced_before_calling(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return _reply({"n": 1})

    c = client(tmp_path, handler, requests_per_day=2)
    c.complete_json([{"role": "user", "content": "1"}], {})
    c.complete_json([{"role": "user", "content": "2"}], {})
    with pytest.raises(LlmError, match="daily request budget"):
        c.complete_json([{"role": "user", "content": "3"}], {})


def test_non_retryable_errors_fail_fast(tmp_path: Path) -> None:
    c = client(tmp_path, lambda _: httpx.Response(401, text="bad key"))
    with pytest.raises(LlmError, match="401"):
        c.complete_json([{"role": "user", "content": "q"}], {})


def test_llm_policy_maps_menu_ids_and_conclusions(
    tmp_path: Path, pack: DomainPack, model: CompiledModel
) -> None:
    replies = iter(
        [
            {"action": "a1", "decision_class": "abstain", "confidence": 0.2},
            {"action": "conclude", "decision_class": "IT_FIX_DNS", "confidence": 0.8},
        ]
    )
    prompts: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        prompts.append(body["messages"][1]["content"])
        assert body["response_format"]["json_schema"]["strict"] is True
        return _reply(next(replies))

    policy = LlmPolicy(client(tmp_path, handler), pack)
    ep = run_episode(pack, model, generate(pack, model, 3), policy)
    assert ep.probes == 1
    assert ep.decision == "IT_FIX_DNS"
    assert ep.confidence == pytest.approx(0.8)
    assert "ACTIONS YOU CAN TAKE NOW" in prompts[0]
    assert "ANSWERS SO FAR" in prompts[1]


def test_llm_failure_counts_as_abstention(
    tmp_path: Path, pack: DomainPack, model: CompiledModel
) -> None:
    policy = LlmPolicy(client(tmp_path, lambda _: httpx.Response(401)), pack)
    ep = run_episode(pack, model, generate(pack, model, 3), policy)
    assert ep.decided is False
    assert ep.failed is True  # a provider failure is not an abstention
    assert policy.errors == 1
    assert summarize([ep])["failed_runs"] == 1
    assert summarize([ep])["n"] == 0


def test_site_rendering_covers_the_pack(pack: DomainPack) -> None:
    text = render_site(pack)
    for c in pack.components:
        assert c.id in text
    for d in pack.decision_classes:
        assert d.id in text


def test_conclusion_type() -> None:
    assert Conclusion(None, 0.1).decision is None


def test_daily_quota_error_fails_fast_and_is_remembered(tmp_path: Path) -> None:
    calls = 0
    body = (
        '{"error": {"code": 429, "message": "You exceeded your current quota ... Quota '
        "exceeded for metric: generativelanguage.googleapis.com/"
        'generate_content_free_tier_requests, limit: 20"}}'
    )

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, text=body)

    c = client(tmp_path, handler)
    with pytest.raises(LlmError, match="daily quota exhausted"):
        c.complete_json([{"role": "user", "content": "1"}], {})
    assert calls == 1  # no retry storm
    with pytest.raises(LlmError, match="daily request budget"):
        c.complete_json([{"role": "user", "content": "2"}], {})
    assert calls == 1  # remembered: not even attempted


def test_model_without_reasoning_control_is_retried_without_it(tmp_path: Path) -> None:
    sent: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        sent.append(body)
        if "reasoning_effort" in body:
            return httpx.Response(
                400,
                text='{"error": {"message": "Thinking level is not supported for this model."}}',
            )
        return _reply({"ok": 1})

    c = client(tmp_path, handler)
    assert c.complete_json([{"role": "user", "content": "q"}], {}).data == {"ok": 1}
    c.complete_json([{"role": "user", "content": "q2"}], {})
    assert ["reasoning_effort" in b for b in sent] == [True, False, False]  # remembered


def test_no_paired_data_is_reported_as_none() -> None:
    assert paired_difference([], [], "probes")["mean"] is None


def test_abstention_recall_counts_only_unidentifiable_scenarios() -> None:
    from pramana_eval.runner import Episode

    def ep(kind: str, identifiable: bool | None, decided: bool, correct: bool) -> Episode:
        return Episode(
            policy="E",
            seed=0,
            kind=kind,
            identifiable=identifiable,
            decided=decided,
            decision="D" if decided else None,
            confidence=0.9,
            correct=correct,
            success=correct or not decided,
            probes=1,
            effort_s=1.0,
            people=1,
            hit_step_limit=False,
        )

    s = summarize(
        [
            ep("access_limited", False, False, False),  # abstained: right
            ep("access_limited", False, True, True),  # decided anyway (luckily right)
            ep("pair", None, True, True),  # a correct pair diagnosis is not a missed abstention
            ep("pair", None, False, False),
        ]
    )
    assert s["abstention_recall"] == 0.5
    assert s["accuracy_when_unidentifiable_but_decided"] == 1.0
    assert s["pair_accuracy"] == 0.5


def test_groq_tokens_per_day_limit_fails_fast(tmp_path: Path) -> None:
    # Groq's daily token cap does not say "quota"; it used to be retried for minutes.
    calls = 0
    body = (
        '{"error": {"message": "Rate limit reached for model `openai/gpt-oss-120b` in '
        "organization `org_x` service tier `on_demand` on tokens per day (TPD): Limit 200000, "
        'Used 199500, Requested 3500. Please try again in 7m12s.", "type": "tokens"}}'
    )

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, text=body, headers={"retry-after": "432"})

    c = client(tmp_path, handler)
    with pytest.raises(LlmError, match="daily quota exhausted"):
        c.complete_json([{"role": "user", "content": "1"}], {})
    assert calls == 1


def test_a_long_retry_after_is_not_slept_through(tmp_path: Path) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, text='{"error": "slow down"}', headers={"retry-after": "900"})

    c = client(tmp_path, handler)
    started = time.monotonic()
    with pytest.raises(LlmError, match="asks to wait 900s"):
        c.complete_json([{"role": "user", "content": "1"}], {})
    assert time.monotonic() - started < 5
    assert calls == 1


def test_pair_outcomes_are_not_claimed_as_full_resolution() -> None:
    from pramana_eval.runner import Episode

    def episode(
        decision: str | None,
        correct: bool,
        identifiable: bool | None,
        full_resolution: bool = False,
    ) -> Episode:
        return Episode(
            "E",
            1,
            "pair",
            identifiable,
            decision is not None,
            decision,
            0.9,
            correct,
            correct or decision is None,
            1,
            1.0,
            1,
            False,
            honest_success=correct or (decision is None and identifiable is False),
            pair_full_resolution=full_resolution,
        )

    useful = episode("DISPATCH_ONE", True, None)
    abstained = episode(None, False, None)
    justified = episode(None, False, False)
    resolved = episode("MULTIPLE_FAULTS", True, None, full_resolution=True)
    result = summarize([useful, abstained, justified, resolved])
    assert result["pair_first_useful_action_rate"] == pytest.approx(1 / 4)
    assert result["pair_full_resolution_rate"] == pytest.approx(1 / 4)
    assert result["pair_resolution_denominator"] == 4
    assert result["justified_abstentions"] == 1
    assert result["abstentions_with_unknown_identifiability"] == 1
    assert result["success_rate"] == 1.0
    assert result["honest_success_rate"] == pytest.approx(3 / 4)
    assert result["justified_abstention_precision"] == pytest.approx(1 / 2)
    assert result["justified_abstention_recall"] == 1.0


def test_pair_episode_runs_repair_verification_and_reopen_loop(
    pack: DomainPack, model: CompiledModel
) -> None:
    scenario = generate(pack, model, 225)
    assert scenario.kind == "pair"
    result = run_episode(pack, model, scenario, Ours())
    assert result.pair_full_resolution is True
    assert result.pair_repairs == 2
    assert result.pair_resolution_extra_probes >= 1


def test_pair_episode_does_not_claim_resolution_after_repair_failures(
    pack: DomainPack, model: CompiledModel
) -> None:
    scenario = generate(pack, model, 225)
    result = run_episode(
        pack,
        model,
        scenario,
        Ours(config=EngineConfig(repair_failure_prior=0.9)),
    )
    assert result.pair_full_resolution is False
    assert result.pair_repairs == 3


def test_paired_statistics_and_holm_against_small_exact_cases() -> None:
    from pramana_eval.statistics import holm, mcnemar_exact, wilcoxon_signed_rank

    assert mcnemar_exact([1, 1, 1, 0], [0, 0, 0, 1]) == pytest.approx(0.625)
    # Three positive differences: only 2 of 8 sign assignments are as extreme.
    assert wilcoxon_signed_rank([1, 2, 3], [0, 0, 0]) == pytest.approx(0.25)
    # Tied absolute differences and zeros are handled by average ranks and dropping zeros.
    assert wilcoxon_signed_rank([1, -1, 0], [0, 0, 0]) == pytest.approx(1.0)
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def test_signed_rank_matches_independent_sign_enumeration() -> None:
    from itertools import product

    from pramana_eval.statistics import wilcoxon_signed_rank

    # Absolute differences have ranks 1, 2.5, 2.5, 4. Enumerate all signs.
    ranks = (1, 2.5, 2.5, 4)
    differences = (1, -2, 2, 4)
    observed = sum(r for r, d in zip(ranks, differences, strict=True) if d > 0)
    distance = abs(observed - sum(ranks) / 2)
    extreme = sum(
        abs(sum(r * sign for r, sign in zip(ranks, signs, strict=True)) - sum(ranks) / 2)
        >= distance
        for signs in product((0, 1), repeat=4)
    )
    assert wilcoxon_signed_rank(differences, (0, 0, 0, 0)) == extreme / 16


def test_primary_family_retains_missing_comparisons() -> None:
    from pramana_eval.__main__ import primary_tests
    from pramana_eval.runner import Episode

    def episode(policy: str, seed: int, success: bool) -> Episode:
        return Episode(
            policy,
            seed,
            "single",
            True,
            True,
            "x",
            0.9,
            success,
            success,
            1,
            1,
            1,
            False,
            honest_success=success,
        )

    result = primary_tests(
        {
            "E_ours": [episode("E", i, True) for i in range(5)],
            "A_checklist": [episode("A", i, False) for i in range(5)],
        }
    )
    assert result["success"]["A_checklist"] == {"n": 5, "p": 0.0625, "p_holm": 0.3125}
    assert result["success"]["B_llm"]["p"] is None


def test_fixed_budget_trajectories_and_artifacts_are_deterministic(
    pack: DomainPack, model: CompiledModel, tmp_path: Path
) -> None:
    from dataclasses import asdict
    from xml.etree import ElementTree

    from pramana_eval.budget import (
        budget_curves,
        calibration,
        run_trajectory,
        stratum_outcomes,
        write_budget_artifacts,
        write_calibration_svg,
    )

    scenarios = [generate(pack, model, seed) for seed in range(5)]
    policies = [Ours(), greedy_entropy(), Checklist(), RandomFeasible()]
    trajectories = {
        policy.name: [run_trajectory(pack, model, scenario, policy, 3) for scenario in scenarios]
        for policy in policies
    }
    curves = budget_curves(trajectories, 3)
    assert {point["budget"] for point in curves["questions"]} == {1, 2, 3}
    assert all(point["n"] == 5 for point in curves["questions"])
    assert all(point["n"] == 5 for point in curves["effort_s"])
    assert trajectories["E_ours"][0] == run_trajectory(pack, model, scenarios[0], Ours(), 3)

    episodes = [asdict(run_episode(pack, model, scenario, Ours())) for scenario in scenarios]
    bins = calibration(episodes)
    assert sum(row["count"] for row in bins) == sum(e["decided"] for e in episodes)
    strata = stratum_outcomes(episodes)
    assert set(strata) == {"single", "pair", "no_fault", "access_limited"}
    assert sum(row["n"] for row in strata.values()) == len(episodes)
    write_budget_artifacts(tmp_path, curves)
    before = (tmp_path / "questions-success.svg").read_bytes()
    write_budget_artifacts(tmp_path, curves)
    assert (tmp_path / "questions-success.svg").read_bytes() == before
    assert (tmp_path / "questions-success.svg").read_text(encoding="utf-8").count("stroke=") > 5
    calibration_path = tmp_path / "reliability.svg"
    write_calibration_svg(calibration_path, bins)
    assert "n=" in calibration_path.read_text(encoding="utf-8")
    assert ElementTree.parse(calibration_path).getroot().tag.endswith("svg")
