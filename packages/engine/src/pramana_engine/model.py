"""Compile a domain pack into the matrices the belief engine and planner use.

The hypothesis space is: every modelled single fault, every *identifiable* pair of faults,
``NO_FAULT`` and ``OPEN_WORLD`` (docs/adr/0008).

* **Pairs.** Two simultaneous faults ``{a, b}`` with prior ``p_a * p_b``. A pair is enumerated
  only if each fault is visible in the presence of the other: its prediction row differs from
  both single-fault rows. A masked pair (``SW_C2.dead`` while ``CB_C2_7.tripped`` already cuts
  its power) predicts exactly what the single fault predicts, so no observation can separate
  them before the masking fault is repaired; post-repair verification catches it instead.
* **Pair decisions.** If both faults call for the same decision class, the pair belongs to it.
  Otherwise it belongs to ``MULTIPLE_FAULTS``: acting on either fault's decision fixes half the
  problem (loss ``wrong / 2``). Acting on ``MULTIPLE_FAULTS`` costs nothing under such a pair
  and the full ``wrong`` loss under a single fault, so it is never a cheap hedge.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from pramana_domain import NO_FAULT, OPEN_WORLD, DomainPack, predict

OPEN_WORLD_PREDICTION = -1
MULTIPLE_FAULTS = "MULTIPLE_FAULTS"
MULTIPLE_FAULTS_LABEL = "Two independent faults: send both teams"


@dataclass(frozen=True)
class Hypothesis:
    id: str
    label: str
    decision_class: str | None
    faults: tuple[tuple[str, str], ...] | None
    """``None`` for OPEN_WORLD: a cause outside the model with no physics."""


@dataclass(frozen=True)
class CompiledModel:
    pack: DomainPack
    hypotheses: tuple[Hypothesis, ...]
    prior: npt.NDArray[np.float64]
    sites: tuple[tuple[str, str], ...]
    site_index: dict[tuple[str, str], int]
    outcomes: dict[str, tuple[str, ...]]
    predictions: npt.NDArray[np.int64]
    """[H, S] index of the predicted outcome at each site; OPEN_WORLD rows are -1."""
    decisions: tuple[str, ...]
    decision_labels: dict[str, str]
    decision_of: npt.NDArray[np.int64]
    """[H] decision index; OPEN_WORLD maps to ``len(decisions)`` (its own bucket)."""
    loss: npt.NDArray[np.float64]
    """[D, H] loss in minutes of acting on decision d when h is true."""
    fault_index: dict[frozenset[tuple[str, str]], int]
    """Hypothesis index of every enumerated fault set (``frozenset()`` is ``NO_FAULT``)."""

    @property
    def open_world_index(self) -> int:
        return len(self.hypotheses) - 1

    def hypothesis_index(self, hid: str) -> int:
        for i, h in enumerate(self.hypotheses):
            if h.id == hid:
                return i
        raise KeyError(hid)


def pair_id(a: tuple[str, str], b: tuple[str, str]) -> str:
    """Stable id of a two-fault hypothesis, e.g. ``AP_3A.dead+CB_C2_7.tripped``."""
    return "+".join(sorted(f"{c}.{m}" for c, m in (a, b)))


def compile_pack(pack: DomainPack, pairs: bool = True) -> CompiledModel:
    sites = tuple((p.id, b.at) for p in pack.probes for b in p.observes)
    site_index = {s: i for i, s in enumerate(sites)}
    outcomes = {p.id: tuple(p.outcomes) for p in pack.probes}

    def row(faults: tuple[tuple[str, str], ...]) -> tuple[int, ...]:
        table = predict(pack, faults)
        return tuple(outcomes[pid].index(table[(pid, loc)]) for pid, loc in sites)

    hyps: list[Hypothesis] = []
    priors: list[float] = []
    rows: list[tuple[int, ...]] = []
    singles = pack.fault_hypotheses()
    single_rows: dict[tuple[str, str], tuple[int, ...]] = {}
    for cid, mode, fm in singles:
        hid = f"{cid}.{mode}"
        hyps.append(Hypothesis(hid, fm.label, pack.decision_of[hid], ((cid, mode),)))
        priors.append(fm.prior)
        single_rows[(cid, mode)] = row(((cid, mode),))
        rows.append(single_rows[(cid, mode)])

    needs_multi = False
    if pairs:
        for (ca, ma, fa), (cb, mb, fb) in itertools.combinations(singles, 2):
            if ca == cb:
                continue  # one component is in one failure mode at a time
            a, b = (ca, ma), (cb, mb)
            r = row((a, b))
            if r in (single_rows[a], single_rows[b]):
                continue  # masked: not identifiable before a repair
            da, db = pack.decision_of[f"{ca}.{ma}"], pack.decision_of[f"{cb}.{mb}"]
            decision = da if da == db else MULTIPLE_FAULTS
            needs_multi |= decision == MULTIPLE_FAULTS
            hyps.append(Hypothesis(pair_id(a, b), f"{fa.label} + {fb.label}", decision, (a, b)))
            priors.append(fa.prior * fb.prior)
            rows.append(r)

    hyps.append(Hypothesis(NO_FAULT, "No building fault", pack.decision_of[NO_FAULT], ()))
    priors.append(pack.no_fault_prior)
    rows.append(row(()))
    hyps.append(Hypothesis(OPEN_WORLD, "Unknown cause (outside the model)", None, None))
    priors.append(pack.open_world_prior)

    prior = np.asarray(priors, dtype=np.float64)
    prior /= prior.sum()

    pred = np.full((len(hyps), len(sites)), OPEN_WORLD_PREDICTION, dtype=np.int64)
    for i, r in enumerate(rows):
        pred[i] = r

    decisions = tuple(d.id for d in pack.decision_classes) + (
        (MULTIPLE_FAULTS,) if needs_multi else ()
    )
    labels = {d.id: d.label for d in pack.decision_classes}
    if needs_multi:
        labels[MULTIPLE_FAULTS] = MULTIPLE_FAULTS_LABEL
    d_index = {d: i for i, d in enumerate(decisions)}
    decision_of = np.asarray(
        [d_index[h.decision_class] if h.decision_class else len(decisions) for h in hyps],
        dtype=np.int64,
    )

    lm = pack.loss_minutes
    loss = np.zeros((len(decisions), len(hyps)), dtype=np.float64)
    for di, d in enumerate(decisions):
        wrong = lm.wrong_by_decision.get(d, lm.wrong_default)
        for hi, h in enumerate(hyps):
            if h.faults is None:
                loss[di, hi] = lm.any_under_open_world
            elif d == MULTIPLE_FAULTS:
                # Not a hedge: under a single fault it sends a team that is not needed and
                # does not name the one that is.
                loss[di, hi] = 0.0 if h.decision_class == MULTIPLE_FAULTS else wrong
            elif h.decision_class == MULTIPLE_FAULTS:
                own = {pack.decision_of[f"{c}.{m}"] for c, m in h.faults}
                loss[di, hi] = wrong / 2 if d in own else wrong
            elif h.decision_class != d:
                loss[di, hi] = wrong

    fault_index = {frozenset(h.faults): i for i, h in enumerate(hyps) if h.faults is not None}
    return CompiledModel(
        pack=pack,
        hypotheses=tuple(hyps),
        prior=prior,
        sites=sites,
        site_index=site_index,
        outcomes=outcomes,
        predictions=pred,
        decisions=decisions,
        decision_labels=labels,
        decision_of=decision_of,
        loss=loss,
        fault_index=fault_index,
    )
