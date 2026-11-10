"""Pair prior mass and repairable-pair share for the campus pack (development evidence).

Post-freeze development diagnosis. Reads only the pack, the compiled engine model and the scenario
generator's fault catalogue; it makes no LLM, provider or database calls.

Run from the repository root:

    uv run python eval/reports/dev-2026-11-10-pairs/tools/pair_coverage.py
"""

from __future__ import annotations

from math import comb

from pramana_domain import load_pack
from pramana_engine import compile_pack


def main() -> None:
    pack = load_pack("campus_block_c")
    model = compile_pack(pack)

    pair_rows = [
        i for i, h in enumerate(model.hypotheses) if h.faults is not None and len(h.faults) == 2
    ]
    pair_mass = float(sum(model.prior[i] for i in pair_rows))
    print(f"compiled hypotheses: {len(model.hypotheses)}")
    print(f"pair hypotheses: {len(pair_rows)}")
    print(f"pair prior mass: {pair_mass:.6f} ({100 * pair_mass:.4f}%)")

    catalogue = [(c, m) for c, m, _ in pack.fault_hypotheses()]
    component_kind = {c.id: c.kind for c in pack.components}

    def repairable(fault: tuple[str, str]) -> bool:
        cid, mode = fault
        return any(
            action.fixes == mode
            and action.target_kind == component_kind[cid]
            and pack.decision_of[f"{cid}.{mode}"] in action.decision_classes
            for action in pack.actions
        )

    repairable_faults = [f for f in catalogue if repairable(f)]
    n, k = len(catalogue), len(repairable_faults)
    print(f"single faults in catalogue: {n}")
    print(f"single faults with a modelled repair: {k} {repairable_faults}")
    share = comb(k, 2) / comb(n, 2)
    print(
        "upper bound on pair scenarios that can be fully resolved "
        f"(both faults repairable, C({k},2)/C({n},2)): {share:.4f} ({100 * share:.2f}%)"
    )


if __name__ == "__main__":
    main()
