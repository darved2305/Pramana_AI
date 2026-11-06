"""Memory growth measurements in the sustained voice load test."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import load_test


def test_memory_slope_uses_the_steady_half_of_samples() -> None:
    samples = [(i * 60.0, 100.0 + i) for i in range(8)]
    assert load_test.memory_slope_mb_per_min(samples) == pytest.approx(1.0)


def test_memory_growth_gate_checks_both_processes_and_requires_samples() -> None:
    flat = [(i * 60.0, 100.0 + (0.1 if i % 2 else 0.0)) for i in range(8)]
    growing = [(i * 60.0, 100.0 + i) for i in range(8)]
    assert load_test.memory_growth_gate(flat, flat, limit_mb_per_min=0.5)
    assert not load_test.memory_growth_gate(growing, flat, limit_mb_per_min=0.5)
    assert not load_test.memory_growth_gate(flat, [], limit_mb_per_min=0.5)
