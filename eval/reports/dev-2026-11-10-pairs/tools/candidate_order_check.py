"""Find development pair episodes where the evaluator's repair candidate order could skip a repair.

``_complete_pair_repair_loop`` takes the first sorted remaining fault. If that fault has no repair
action, it returns incomplete even when another remaining fault has one. This script checks the
first candidate choice of every pair episode with a `MULTIPLE_FAULTS` decision and no repair
attempt in ``before/episodes.csv``, for E and D. In those rows the first choice is the only one
made, so the CSV row fully determines it. Later choices, after a failed repair, are not covered
here; they need a trace.

Run from the repository root:

    uv run python eval/reports/dev-2026-11-10-pairs/tools/candidate_order_check.py
"""

from __future__ import annotations

import csv
from pathlib import Path

from pramana_domain import load_pack
from pramana_engine import MULTIPLE_FAULTS, compile_pack
from pramana_eval.scenarios import generate

HERE = Path(__file__).resolve().parent
EPISODES = HERE.parent / "before" / "episodes.csv"


def main() -> None:
    pack = load_pack("campus_block_c")
    model = compile_pack(pack)

    def has_action(fault: tuple[str, str]) -> bool:
        cid, mode = fault
        kind = pack.component_by_id[cid].kind
        return any(
            action.fixes == mode
            and action.target_kind == kind
            and pack.decision_of[f"{cid}.{mode}"] in action.decision_classes
            for action in pack.actions
        )

    with EPISODES.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    for policy in ("E_ours", "D_greedy_entropy"):
        pairs = [r for r in rows if r["policy"] == policy and r["kind"] == "pair"]
        eligible = [r for r in pairs if r["decision"] == MULTIPLE_FAULTS and r["pair_repairs"] == "0"]
        affected = []
        for row in eligible:
            faults = sorted(generate(pack, model, int(row["seed"])).faults)
            if not has_action(faults[0]) and any(has_action(f) for f in faults[1:]):
                affected.append((int(row["seed"]), faults))
        print(
            f"{policy}: pair episodes={len(pairs)} eligible={len(eligible)} "
            f"affected={len(affected)} {affected}"
        )


if __name__ == "__main__":
    main()
