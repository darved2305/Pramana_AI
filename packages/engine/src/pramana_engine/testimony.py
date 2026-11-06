"""Explaining why two people's answers disagree (PRODUCT.md U4, plan N06).

When two people report different things for the same kind of observation, there are two
readings: both are right, because the cause affects one of their places and not the other
("different access points"), or one of them is mistaken. The engine already weighs both inside
the posterior; this module only makes that weighing visible:

- ``p_both_right``: posterior probability of the causes under which both answers are exactly
  what a reliable person would see;
- ``p_mistaken`` per side: posterior probability of the causes under which that side's answer
  is not what is there to see;
- the most probable reconciling cause, and which of its faults only one side depends on (the
  component that makes the two places differ).

Pure: computed from the compiled model and a posterior. No text: the core words it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from .belief import FloatArray
from .model import OPEN_WORLD_PREDICTION, CompiledModel

BOTH_RIGHT_AT = 0.5
"""Above this, the disagreement is presented as "both can be right"."""


@dataclass(frozen=True)
class Side:
    participant_id: str
    probe_id: str
    location_id: str
    outcome: str
    p_mistaken: float
    """P(this answer is not what is there to see), from the current posterior."""


@dataclass(frozen=True)
class Disagreement:
    earlier: Side
    new: Side
    p_both_right: float
    reconciling: str | None
    """Most probable cause under which both answers are right (a hypothesis id)."""
    reconciling_label: str | None
    only_one_depends: tuple[tuple[Literal["earlier", "new"], str], ...]
    """Faults of the reconciling cause that change what one side sees and not the other:
    (which side depends on it, component id)."""

    @property
    def kind(self) -> Literal["both_right", "one_mistaken"]:
        return "both_right" if self.p_both_right >= BOTH_RIGHT_AT else "one_mistaken"

    @property
    def likelier_mistaken(self) -> Side | None:
        """The side more likely to be mistaken, when they are not equally likely."""
        if abs(self.earlier.p_mistaken - self.new.p_mistaken) < 1e-9:
            return None
        return self.earlier if self.earlier.p_mistaken > self.new.p_mistaken else self.new


def explain(
    model: CompiledModel,
    posterior: FloatArray,
    earlier: tuple[str, str, str, str],
    new: tuple[str, str, str, str],
) -> Disagreement:
    """``earlier`` and ``new`` are (participant_id, probe_id, location_id, outcome)."""
    pred = model.predictions
    known = pred[:, 0] != OPEN_WORLD_PREDICTION
    fits: list[np.ndarray] = []
    for _, probe_id, location_id, outcome in (earlier, new):
        site = model.site_index[(probe_id, location_id)]
        fits.append(pred[:, site] == model.outcomes[probe_id].index(outcome))
    both = fits[0] & fits[1] & known
    p_both = float(posterior[both].sum())
    sides = [
        Side(*key, p_mistaken=float(posterior[known & ~fit].sum()))
        for key, fit in zip((earlier, new), fits, strict=True)
    ]
    reconciling: str | None = None
    label: str | None = None
    depends: list[tuple[Literal["earlier", "new"], str]] = []
    if both.any():
        h = int(np.argmax(np.where(both, posterior, -1.0)))
        hyp = model.hypotheses[h]
        reconciling, label = hyp.id, hyp.label
        none = model.fault_index[frozenset()]
        for fault in hyp.faults or ():
            single = model.fault_index.get(frozenset({fault}))
            if single is None:
                continue
            affects = []
            for _, probe_id, location_id, _ in (earlier, new):
                site = model.site_index[(probe_id, location_id)]
                affects.append(bool(pred[single, site] != pred[none, site]))
            if affects[0] != affects[1]:
                depends.append(("earlier" if affects[0] else "new", fault[0]))
    return Disagreement(sides[0], sides[1], p_both, reconciling, label, tuple(depends))
