"""Word the engine's reading of a disagreement for the console (English, operators only).

Every number comes from ``pramana_engine.testimony``; every name from the pack and the
participant list. Nothing is inferred here.
"""

from __future__ import annotations

from pramana_contracts import DependsOn, DisagreementSide, DisagreementView
from pramana_domain import DomainPack
from pramana_engine import Disagreement

MENTION_BOTH_RIGHT = 0.05
"""Below this, "both can be right" is not worth saying."""


def _pct(p: float) -> str:
    return f"{round(100 * p)}%"


def _place(pack: DomainPack, location_id: str) -> str:
    return pack.location_by_id[location_id].label.en


def disagreement_view(
    pack: DomainPack, names: dict[str, str], d: Disagreement, observation_id: str
) -> DisagreementView:
    sides = {"earlier": d.earlier, "new": d.new}
    depends = [
        DependsOn(side=side, component_id=cid, component_label=pack.component_by_id[cid].label)
        for side, cid in d.only_one_depends
    ]
    who = {k: names.get(s.participant_id, s.participant_id) for k, s in sides.items()}
    parts: list[str] = []
    if d.reconciling_label is not None and d.p_both_right >= MENTION_BOTH_RIGHT:
        line = f"Both can be right if the cause is: {d.reconciling_label} ({_pct(d.p_both_right)})."
        for dep in depends:
            side = sides[dep.side]
            other = sides["new" if dep.side == "earlier" else "earlier"]
            line += (
                f" Only {who[dep.side]}'s place ({_place(pack, side.location_id)}) depends on"
                f" {dep.component_label}"
            )
            covered = [
                pack.component_by_id[ap].label
                for ap in pack.location_by_id[other.location_id].wifi_coverage
                if ap != dep.component_id
            ]
            comp = pack.component_by_id[dep.component_id]
            if comp.kind == "ap" and covered:
                line += (
                    f"; {_place(pack, other.location_id)} is also covered by {', '.join(covered)}"
                )
            line += "."
        parts.append(line)
    else:
        parts.append("No likely cause makes both answers right.")
    mistaken = d.likelier_mistaken
    if mistaken is not None:
        key = "earlier" if mistaken is d.earlier else "new"
        p = _pct(mistaken.p_mistaken)
        parts.append(f"If one of them is mistaken, it is more likely {who[key]} ({p}).")
    return DisagreementView(
        observation_id=observation_id,
        earlier=DisagreementSide(**_side(d.earlier)),
        new=DisagreementSide(**_side(d.new)),
        kind=d.kind,
        p_both_right=d.p_both_right,
        reconciling_hypothesis=d.reconciling,
        reconciling_label=d.reconciling_label,
        only_one_depends=depends,
        explanation=" ".join(parts),
    )


def _side(s: object) -> dict[str, object]:
    return {
        k: getattr(s, k)
        for k in ("participant_id", "probe_id", "location_id", "outcome", "p_mistaken")
    }
