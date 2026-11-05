"""Bayesian diagnosis engine and value-of-information planner. Pure: no I/O, no clock."""

from .config import EngineConfig
from .engine import Engine, Evidence, EvidenceError, ObserveResult
from .model import MULTIPLE_FAULTS, CompiledModel, Hypothesis, compile_pack

MODEL_VERSION = "2"
"""Version of the probability model (hypotheses, likelihoods, reliability). Bump it whenever
a change makes the same evidence produce a different belief, so a replay can tell an engine
upgrade from a corrupted log. "1": single faults, fixed reliability (ADR 0004). "2": fault
pairs and reliability integrated out (ADR 0008)."""

__all__ = [
    "MODEL_VERSION",
    "MULTIPLE_FAULTS",
    "CompiledModel",
    "Engine",
    "EngineConfig",
    "Evidence",
    "EvidenceError",
    "Hypothesis",
    "ObserveResult",
    "compile_pack",
]
