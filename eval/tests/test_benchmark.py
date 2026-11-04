"""Benchmark harness tests. LLM calls are mocked at the HTTP layer (no network, no quota)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import pytest

from pramana_core.llm import LlmClient, LlmError, ProviderLimits, _duration_s
from pramana_domain import DomainPack, load_pack
from pramana_engine import CompiledModel, compile_pack
from pramana_eval.llm_policy import LlmPolicy, render_site
from pramana_eval.policies import Checklist, Conclusion, Ours, RandomFeasible, greedy_entropy
from pramana_eval.runner import paired_difference, run_episode, summarize
from pramana_eval.scenarios import Answers, generate


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
