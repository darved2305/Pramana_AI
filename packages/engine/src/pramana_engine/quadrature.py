"""Gauss-Jacobi quadrature for a Beta-distributed reliability.

A participant's reliability for a probe class is unknown. Its prior is
``r = 0.5 + 0.5 x`` with ``x ~ Beta(a, b)``, so ``r`` lives in ``(0.5, 1)`` (better than chance,
never perfect) and has the configured mean.

The likelihood of ``n`` answers given a hypothesis is a polynomial of degree ``n`` in ``r``:
each answer contributes ``w * r + c`` or ``w * (1 - r) / (m - 1) + c``. A ``K``-node Gauss rule
for the Beta weight integrates polynomials of degree ``<= 2K - 1`` exactly, so with ``K = 8`` the
marginal likelihood is *exact* (to floating point) for up to 15 answers by one person in one
probe class, which exceeds the per-person question budget.

Nodes come from the Golub-Welsch algorithm: the eigenvalues of the symmetric Jacobi matrix
built from the three-term recurrence of the Jacobi polynomials, with weights from the first
components of the eigenvectors. Only numpy is needed.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


def gauss_jacobi(n: int, alpha: float, beta: float) -> tuple[FloatArray, FloatArray]:
    """Nodes on ``[-1, 1]`` and normalised weights for the weight ``(1-t)^alpha (1+t)^beta``."""
    if n < 1:
        raise ValueError("need at least one node")
    if alpha <= -1 or beta <= -1:
        raise ValueError("alpha and beta must exceed -1")
    k = np.arange(n, dtype=np.float64)
    ab = alpha + beta
    diag = np.empty(n)
    diag[0] = (beta - alpha) / (ab + 2.0)
    if n > 1:
        kk = k[1:]
        s = 2.0 * kk + ab
        diag[1:] = (beta**2 - alpha**2) / (s * (s + 2.0))
    kk = np.arange(1, n, dtype=np.float64)
    s = 2.0 * kk + ab
    off2 = np.empty(n - 1)
    if n > 1:
        # At k=1, k+ab and s-1 are the same factor. Cancel it
        # analytically, including near ab=-1 where division loses accuracy.
        off2[0] = 4.0 * (1.0 + alpha) * (1.0 + beta) / (s[0] ** 2 * (s[0] + 1.0))
        off2[1:] = (
            4.0
            * kk[1:]
            * (kk[1:] + alpha)
            * (kk[1:] + beta)
            * (kk[1:] + ab)
            / (s[1:] ** 2 * (s[1:] + 1.0) * (s[1:] - 1.0))
        )
    jac = np.diag(diag) + np.diag(np.sqrt(off2), 1) + np.diag(np.sqrt(off2), -1)
    nodes, vecs = np.linalg.eigh(jac)
    weights = vecs[0] ** 2
    weights /= weights.sum()
    return nodes, weights


def _gauss_beta_jacobi(n: int, mean: float, concentration: float) -> tuple[FloatArray, FloatArray]:
    """Jacobi rule for Beta shapes, retaining the parameters lost by alpha = shape - 1.

    Factoring the recurrence in terms of ``mean`` and ``concentration`` avoids cancellation
    when a shape is smaller than one ulp at 1, and avoids squaring very large shapes.
    """
    if n < 1:
        raise ValueError("need at least one node")
    mu = (mean - 0.5) / 0.5
    balance = 2.0 * mu - 1.0
    k = np.arange(n, dtype=np.float64)
    diag = np.empty(n)
    diag[0] = balance
    if n > 1:
        kk = k[1:]
        s = 2.0 * (kk - 1.0) + concentration
        diag[1:] = balance * (concentration / s) * ((concentration - 2.0) / (s + 2.0))
    off2 = np.empty(n - 1)
    if n > 1:
        off2[0] = 4.0 * mu * (1.0 - mu) / (1.0 + concentration)
    if n > 2:
        kk = k[2:]
        s = 2.0 * (kk - 1.0) + concentration
        u = kk + (1.0 - mu) * concentration - 1.0
        v = kk + mu * concentration - 1.0
        w = (kk - 2.0) + concentration
        off2[1:] = (4.0 * kk / s) * (u / s) * (v / s) * (w / s) / ((s + 1.0) / s) / ((s - 1.0) / s)
    jac = np.diag(diag) + np.diag(np.sqrt(off2), 1) + np.diag(np.sqrt(off2), -1)
    nodes, vecs = np.linalg.eigh(jac)
    weights = np.maximum(vecs[0] ** 2, np.finfo(np.float64).tiny)
    weights /= weights.sum()
    return nodes, weights


@lru_cache(maxsize=256)
def beta_reliability_rule(
    mean: float, concentration: float, n: int
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """(reliability nodes, probability weights) for ``r = 0.5 + 0.5 x``, ``x ~ Beta(a, b)``.

    ``mean`` is E[r] in (0.5, 1); ``concentration`` is ``a + b``.
    """
    if not 0.5 < mean < 1.0:
        raise ValueError("mean reliability must be in (0.5, 1)")
    if concentration <= 0:
        raise ValueError("concentration must be positive")
    # x ~ Beta(a, b) on [0, 1] <-> t = 2x - 1 with Jacobi shapes b-1 and a-1.
    t, w = _gauss_beta_jacobi(n, mean, concentration)
    x = (t + 1.0) / 2.0
    r = 0.5 + 0.5 * x
    return tuple(float(v) for v in r), tuple(float(v) for v in w)


def beta_moments(a: float, b: float, degree: int) -> FloatArray:
    """E[x^k] for x ~ Beta(a, b), k = 0..degree (reference values for tests)."""
    out = np.ones(degree + 1)
    for k in range(1, degree + 1):
        out[k] = out[k - 1] * (a + k - 1) / (a + b + k - 1)
    return out
