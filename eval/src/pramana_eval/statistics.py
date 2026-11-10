"""Paired tests and Holm correction for benchmark comparisons."""

from __future__ import annotations

import math
from collections.abc import Sequence


def mcnemar_exact(a: Sequence[float], b: Sequence[float]) -> float:
    """Two-sided exact binomial test of discordant paired binary outcomes."""
    if len(a) != len(b):
        raise ValueError("paired samples must have equal lengths")
    if any(x not in (0, 1) or y not in (0, 1) for x, y in zip(a, b, strict=True)):
        raise ValueError("McNemar requires binary outcomes")
    wins = sum(x > y for x, y in zip(a, b, strict=True))
    losses = sum(x < y for x, y in zip(a, b, strict=True))
    n = wins + losses
    if not n:
        return 1.0
    return float(min(1.0, 2 * sum(math.comb(n, k) for k in range(min(wins, losses) + 1)) / 2**n))


def wilcoxon_signed_rank(a: Sequence[float], b: Sequence[float]) -> float:
    """Two-sided signed rank test, exact sign enumeration up to 25 nonzero pairs.

    Larger samples use a continuity-corrected normal approximation with tie-corrected variance.
    Zero differences are dropped. Average ranks are used for ties.
    """
    if len(a) != len(b):
        raise ValueError("paired samples must have equal lengths")
    diffs = sorted((x - y for x, y in zip(a, b, strict=True) if x != y), key=abs)
    if not diffs:
        return 1.0
    ranks: list[float] = [0.0] * len(diffs)
    i = 0
    while i < len(diffs):
        j = i + 1
        while j < len(diffs) and abs(diffs[j]) == abs(diffs[i]):
            j += 1
        ranks[i:j] = [(i + 1 + j) / 2] * (j - i)
        i = j
    positive = sum(rank for rank, d in zip(ranks, diffs, strict=True) if d > 0)
    total = sum(ranks)
    if len(diffs) <= 25:
        # Integer doubled ranks permit exact enumeration, including tied ranks.
        counts = [1]
        for rank in ranks:
            k = int(2 * rank)
            counts += [0] * k
            for s in range(len(counts) - 1, k - 1, -1):
                counts[s] += counts[s - k]
        tail = round(2 * min(positive, total - positive))
        return float(min(1.0, 2 * sum(counts[: tail + 1]) / 2 ** len(diffs)))
    variance = sum(rank * rank for rank in ranks) / 4
    distance = max(0.0, abs(positive - total / 2) - 0.5)
    return math.erfc(distance / math.sqrt(2 * variance))


def holm(p_values: Sequence[float]) -> list[float]:
    """Holm adjusted p-values in the original order."""
    if any(not 0 <= p <= 1 for p in p_values):
        raise ValueError("p-values must be in [0, 1]")
    adjusted = [0.0] * len(p_values)
    previous = 0.0
    for rank, index in enumerate(sorted(range(len(p_values)), key=p_values.__getitem__)):
        previous = max(previous, min(1.0, (len(p_values) - rank) * p_values[index]))
        adjusted[index] = previous
    return adjusted
