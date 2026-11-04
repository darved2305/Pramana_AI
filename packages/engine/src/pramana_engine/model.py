"""Compile a domain pack into the matrices the belief engine and planner use.

The hypothesis space is: every modelled single fault, ``NO_FAULT``, and ``OPEN_WORLD``. Multiple
simultaneous faults are not enumerated in this version; a world with two faults is explained by
whichever single fault fits best or by ``OPEN_WORLD`` (documented limitation, docs/adr/0004).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from pramana_domain import NO_FAULT, OPEN_WORLD, DomainPack, predict

OPEN_WORLD_PREDICTION = -1


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

    @property
    def open_world_index(self) -> int:
        return len(self.hypotheses) - 1

    def hypothesis_index(self, hid: str) -> int:
        for i, h in enumerate(self.hypotheses):
            if h.id == hid:
                return i
        raise KeyError(hid)


def compile_pack(pack: DomainPack) -> CompiledModel:
    hyps: list[Hypothesis] = []
    priors: list[float] = []
    for cid, mode, fm in pack.fault_hypotheses():
        hid = f"{cid}.{mode}"
        hyps.append(Hypothesis(hid, fm.label, pack.decision_of[hid], ((cid, mode),)))
        priors.append(fm.prior)
    hyps.append(Hypothesis(NO_FAULT, "No building fault", pack.decision_of[NO_FAULT], ()))
    priors.append(pack.no_fault_prior)
    hyps.append(Hypothesis(OPEN_WORLD, "Unknown cause (outside the model)", None, None))
    priors.append(pack.open_world_prior)

    prior = np.asarray(priors, dtype=np.float64)
    prior /= prior.sum()

    sites = tuple((p.id, b.at) for p in pack.probes for b in p.observes)
    site_index = {s: i for i, s in enumerate(sites)}
    outcomes = {p.id: tuple(p.outcomes) for p in pack.probes}

    pred = np.full((len(hyps), len(sites)), OPEN_WORLD_PREDICTION, dtype=np.int64)
    for i, h in enumerate(hyps):
        if h.faults is None:
            continue
        table = predict(pack, h.faults)
        for j, (pid, loc) in enumerate(sites):
            pred[i, j] = outcomes[pid].index(table[(pid, loc)])

    decisions = tuple(d.id for d in pack.decision_classes)
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
            elif h.decision_class != d:
                loss[di, hi] = wrong

    return CompiledModel(
        pack=pack,
        hypotheses=tuple(hyps),
        prior=prior,
        sites=sites,
        site_index=site_index,
        outcomes=outcomes,
        predictions=pred,
        decisions=decisions,
        decision_labels={d.id: d.label for d in pack.decision_classes},
        decision_of=decision_of,
        loss=loss,
    )
