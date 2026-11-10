"""Print the engine and simulated-answer events for selected pair episodes (development evidence).

Post-freeze development diagnosis, seeds 60000-60299 only. The script wraps Engine.plan,
Engine.observe, Engine.apply_intervention, Engine.reopen, Answers.ask and the policy's next step,
logs every call and returns the original result, so engine state and control flow are unchanged.

Run from the repository root:

    uv run python eval/reports/dev-2026-11-10-pairs/tools/trace_pair_episodes.py > pair-traces-raw.txt
"""

from __future__ import annotations

import sys

from pramana_domain import load_pack
from pramana_engine import Engine, compile_pack
from pramana_eval.policies import Ours
from pramana_eval.runner import run_episode
from pramana_eval.scenarios import Answers, generate

DEFAULT_SEEDS = (60009, 60058, 60098, 60236)

current_seed: int | None = None
trace_seeds: set[int] = set()
phase: dict[int, str] = {}


def _phase(engine: Engine) -> str:
    return phase.get(id(engine), "initial diagnosis")


orig_plan = Engine.plan
orig_observe = Engine.observe
orig_apply = Engine.apply_intervention
orig_reopen = Engine.reopen
orig_ask = Answers.ask


def traced_plan(self: Engine):  # type: ignore[no-untyped-def]
    result = orig_plan(self)
    if current_seed in trace_seeds and _phase(self) != "initial diagnosis":
        rep = self.snapshot().repair
        p_fixed = f"{rep.fixed_probability:.3f}" if rep else "-"
        action = result.action.model_dump() if result.action else None
        print(
            f"  PLAN [{_phase(self)}] {result.kind} rule={result.rule!r} "
            f"p_fixed={p_fixed} action={action} decision={result.decision_class!r}"
        )
    return result


def traced_observe(self: Engine, ev):  # type: ignore[no-untyped-def]
    result = orig_observe(self, ev)
    if current_seed in trace_seeds:
        print(
            f"  OBS [{_phase(self)}] {ev.participant_id}/{ev.probe_id}@{ev.location_id}"
            f"={ev.outcome} used={result.used_as_evidence} reason={result.reason}"
        )
    return result


def traced_apply(self: Engine, action_id, target, participant_id=None):  # type: ignore[no-untyped-def]
    if current_seed in trace_seeds:
        print(f"  REPAIR request [{_phase(self)}] action={action_id} target={target}")
    result = orig_apply(self, action_id, target, participant_id)
    phase[id(self)] = "verification 1"
    if current_seed in trace_seeds:
        rep = self.snapshot().repair
        print(
            f"  REPAIR state p_fixed={rep.fixed_probability:.3f} "
            f"post_obs={rep.post_repair_observations}"
        )
    return result


def traced_reopen(self: Engine):  # type: ignore[no-untyped-def]
    if current_seed in trace_seeds:
        rep = self.snapshot().repair
        print(
            f"  REOPEN [{_phase(self)}] p_fixed={rep.fixed_probability:.3f} "
            f"post_obs={rep.post_repair_observations}"
        )
    result = orig_reopen(self)
    n = sum(1 for v in phase.values() if v.startswith("follow-up diagnosis")) + 1
    phase[id(self)] = f"follow-up diagnosis {n}"
    return result


def traced_ask(self: Answers, participant_id, probe_id, location_id):  # type: ignore[no-untyped-def]
    truth = self.world.observe(self.pack.probe_by_id[probe_id], location_id)
    ev = orig_ask(self, participant_id, probe_id, location_id)
    if current_seed in trace_seeds:
        stage = next(
            (v for v in phase.values() if v.startswith(("verification", "follow-up diagnosis"))),
            "initial diagnosis",
        )
        print(
            f"  ANSWER [{stage}] {participant_id}/{probe_id}@{location_id}: "
            f"truth={truth}, said={ev.outcome}"
        )
    return ev


Engine.plan = traced_plan  # type: ignore[method-assign]
Engine.observe = traced_observe  # type: ignore[method-assign]
Engine.apply_intervention = traced_apply  # type: ignore[method-assign]
Engine.reopen = traced_reopen  # type: ignore[method-assign]
Answers.ask = traced_ask  # type: ignore[method-assign]


def main(argv: list[str]) -> None:
    global current_seed
    seeds = tuple(int(a) for a in argv) or DEFAULT_SEEDS
    if any(not 60000 <= s <= 60299 for s in seeds):
        raise SystemExit("seeds must lie in the development range 60000-60299")
    trace_seeds.update(seeds)
    pack = load_pack("campus_block_c")
    model = compile_pack(pack)
    for seed in sorted(seeds):
        current_seed = seed
        phase.clear()
        scenario = generate(pack, model, seed)
        print(
            f"\n=== EPISODE E/{seed} faults={scenario.faults} "
            f"true_decisions={sorted(scenario.true_decisions)} ==="
        )
        policy = Ours()
        base_next = policy.next

        def wrapped_next(engine, history, _base=base_next):  # type: ignore[no-untyped-def]
            step = _base(engine, history)
            if current_seed in trace_seeds:
                print(f"  POLICY [{_phase(engine)}] -> {step}")
            return step

        policy.next = wrapped_next  # type: ignore[method-assign]
        result = run_episode(pack, model, scenario, policy)
        print(
            f"  RESULT decision={result.decision!r} correct={result.correct} "
            f"resolved={result.pair_full_resolution} repairs={result.pair_repairs} "
            f"extra_probes={result.pair_resolution_extra_probes}"
        )


if __name__ == "__main__":
    main(sys.argv[1:])
