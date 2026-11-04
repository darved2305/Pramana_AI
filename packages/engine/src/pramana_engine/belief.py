"""Observation model and exact Bayesian posterior over the hypothesis space.

Observation model for an answer ``o`` to a probe with outcome set ``O`` (size ``m``) at a site
where hypothesis ``h`` predicts the true observable ``y_h``:

* Perception noise: ``M(o | y; r) = r`` if ``o == y`` else ``(1 - r) / (m - 1)``, where ``r`` is
  the participant's reliability for the probe class. ``r`` is unknown and integrated out per
  person and probe class (docs/adr/0008). ``M`` is linear in ``r``, so the predictive
  distribution of a new answer under ``h`` is exactly ``M(o | y_h; E[r | h, answers so far])``.
* Hedging and hearsay mix toward uniform: ``M'(o | y) = w * M(o | y; r) + (1 - w) / m`` with
  ``w`` = hedge weight (times the hearsay factor for relayed answers).
* ``OPEN_WORLD`` has no physics, so its predictive distribution is uniform: ``P(o | OW) = 1/m``.
  This is a proper likelihood (it sums to one over outcomes), so OPEN_WORLD gains mass exactly
  when the evidence is better explained by "anything could happen" than by every modelled cause.

Given ``h`` and the reliabilities, answers are conditionally independent; with reliability
integrated out, one person's answers within a probe class are correlated through it. Repeated
answers to the same site by the same participant are *not* independent evidence, so the engine
keeps only the latest one.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

from .model import OPEN_WORLD_PREDICTION, CompiledModel

FloatArray = npt.NDArray[np.float64]


def likelihood_matrix(
    model: CompiledModel,
    site: int,
    reliability: float | FloatArray,
    weight: float,
    predictions: npt.NDArray[np.int64] | None = None,
) -> FloatArray:
    """``L[o, h] = P(answer o | h)`` for one site. Columns sum to one.

    ``reliability`` is a scalar or one value per hypothesis (the person's posterior mean
    reliability under that hypothesis). ``predictions`` overrides the compiled table.
    """
    pid = model.sites[site][0]
    m = len(model.outcomes[pid])
    if not 0.0 <= weight <= 1.0:
        raise ValueError("weight must be in [0, 1]")
    pred = (model.predictions if predictions is None else predictions)[:, site]
    r = np.broadcast_to(np.asarray(reliability, dtype=np.float64), pred.shape)
    lik = np.repeat(((1.0 - r) / (m - 1))[None, :], m, axis=0)
    known = pred != OPEN_WORLD_PREDICTION
    idx = np.nonzero(known)[0]
    lik[pred[known], idx] = r[idx]
    lik = weight * lik + (1.0 - weight) / m
    lik[:, ~known] = 1.0 / m
    return lik


def log_posterior(model: CompiledModel, log_terms: FloatArray) -> FloatArray:
    """Normalised posterior from the prior and a summed log-likelihood vector (log-sum-exp)."""
    logp = np.log(model.prior) + log_terms
    logp -= np.max(logp)
    p = np.exp(logp)
    out: FloatArray = p / p.sum()
    return out


def entropy_bits(p: FloatArray) -> float:
    nz = p[p > 0]
    return float(-(nz * np.log2(nz)).sum())


def decision_marginal(model: CompiledModel, p: FloatArray) -> FloatArray:
    """P(decision class) with OPEN_WORLD as an extra final bucket."""
    out: FloatArray = np.bincount(
        model.decision_of, weights=p, minlength=len(model.decisions) + 1
    ).astype(np.float64)
    return out


def expected_loss(model: CompiledModel, p: FloatArray) -> tuple[int, float]:
    """(index of the loss-minimising decision, its expected loss in minutes)."""
    losses = model.loss @ p
    best = int(np.argmin(losses))
    return best, float(losses[best])
