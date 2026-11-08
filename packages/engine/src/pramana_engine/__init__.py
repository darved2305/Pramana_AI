"""Bayesian diagnosis engine and value-of-information planner. Pure: no I/O, no clock."""

from .config import EngineConfig
from .engine import Engine, Evidence, EvidenceError, ObserveResult, Presence
from .forecast import Forecast, forecast
from .mapdrift import map_drift
from .model import MULTIPLE_FAULTS, CompiledModel, Hypothesis, compile_pack
from .scheduler import Schedule, schedule
from .testimony import Disagreement, Side

MODEL_VERSION = "2"
"""Version of the probability model (hypotheses, likelihoods, reliability). Bump it whenever
a change makes the same evidence produce a different belief, so a replay can tell an engine
upgrade from a corrupted log. "1": single faults, fixed reliability (ADR 0004). "2": fault
pairs and reliability integrated out (ADR 0008)."""

__all__ = [
    "MODEL_VERSION",
    "MULTIPLE_FAULTS",
    "CompiledModel",
    "Disagreement",
    "Engine",
    "EngineConfig",
    "Evidence",
    "EvidenceError",
    "Forecast",
    "Hypothesis",
    "ObserveResult",
    "Presence",
    "Schedule",
    "Side",
    "compile_pack",
    "forecast",
    "map_drift",
    "schedule",
]
