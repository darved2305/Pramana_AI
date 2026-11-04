"""Engine configuration. Values are initial settings to be calibrated by the evaluation harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

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
    repair_failure_prior: float = 0.1
    """P(a repair did not take effect even though its target was the cause)."""
    verified_threshold: float = 0.97
    not_fixed_threshold: float = 0.10
    verification_min_bits: float = 0.01
    verification_unused_bonus: float = 1.25
    """Score multiplier for observations not used during diagnosis ("risky" predictions)."""
    verification_extra_questions: int = 2
    """Extra questions each person may be asked after a repair, beyond their budget."""
    decision_focus: bool = True
    """Rank by information about the *decision* (EIG_D). Off: information about the cause only
    (the "greedy entropy" baseline and the decision-focus ablation)."""
    selection: Literal["score", "net_value"] = "score"
    """How to choose among questions worth asking: by information per second ("score") or by
    net decision value (expected loss avoided minus effort)."""
    cost_aware: bool = True
    """Divide information by the participant's effort. Off: ignore cost (ablation/baseline)."""

    def __post_init__(self) -> None:
        if not 0 < self.tau_lo <= self.tau_hi < 1:
            raise ValueError("require 0 < tau_lo <= tau_hi < 1")
        for key, r in self.reliability.items():
            if not 0.5 < r < 1:
                raise ValueError(f"reliability {key} must be in (0.5, 1)")
