"""Engine configuration. Values are initial settings to be calibrated by the evaluation harness."""

from __future__ import annotations

from dataclasses import dataclass, field

from pramana_contracts import Hedge, Skill

DEFAULT_RELIABILITY: dict[tuple[Skill, str], float] = {
    # P(answer equals the true observable) for a direct, certain answer, by skill and probe class.
    # Fixed per participant type: a single incident does not contain enough data to identify an
    # individual's reliability, so it is not learned online (see docs/adr/0004).
    (Skill.LAY, "device"): 0.92,
    (Skill.LAY, "visual"): 0.85,
    (Skill.LAY, "panel"): 0.60,
    (Skill.ACCESS, "device"): 0.93,
    (Skill.ACCESS, "visual"): 0.90,
    (Skill.ACCESS, "panel"): 0.75,
    (Skill.TECHNICIAN, "device"): 0.95,
    (Skill.TECHNICIAN, "visual"): 0.95,
    (Skill.TECHNICIAN, "panel"): 0.97,
}

DEFAULT_HEDGE_WEIGHT: dict[Hedge, float] = {
    Hedge.CERTAIN: 1.0,
    Hedge.PROBABLE: 0.7,
    Hedge.UNSURE: 0.35,
}


@dataclass(frozen=True)
class EngineConfig:
    tau_hi: float = 0.95
    """Decide when the leading decision class reaches this probability."""
    tau_lo: float = 0.80
    """When no question is worth asking, decide (moderate confidence) above this, else abstain."""
    open_world_abstain: float = 0.25
    """Abstain when the evidence fits no modelled cause with at least this probability."""
    eta: float = 0.1
    """Weight of hypothesis-level information gain added to decision-level gain."""
    lambda_min_per_s: float = 1.0 / 60.0
    """Exchange rate between participant effort (seconds) and decision loss (minutes)."""
    setup_s: float = 15.0
    fatigue_s: float = 5.0
    hearsay_factor: float = 0.5
    voice_weight: float = 0.9
    """Extra mixing toward uniform for spoken answers. Speech recognition adds an error channel
    with no confidence signal: on real short code-mixed turns, a few were transcribed
    confidently as different words (private evaluation, 2026-11-04)."""
    reliability: dict[tuple[Skill, str], float] = field(
        default_factory=lambda: dict(DEFAULT_RELIABILITY)
    )
    hedge_weight: dict[Hedge, float] = field(default_factory=lambda: dict(DEFAULT_HEDGE_WEIGHT))
    top_candidates: int = 8
    top_infeasible: int = 5
    planning_reliability: float = 0.95
    """Reliability assumed when valuing actions nobody present can perform (abstention report)."""

    def __post_init__(self) -> None:
        if not 0 < self.tau_lo <= self.tau_hi < 1:
            raise ValueError("require 0 < tau_lo <= tau_hi < 1")
        for key, r in self.reliability.items():
            if not 0.5 < r < 1:
                raise ValueError(f"reliability {key} must be in (0.5, 1)")
