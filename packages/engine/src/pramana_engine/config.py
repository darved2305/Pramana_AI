"""Engine configuration. Values are initial settings to be calibrated by the evaluation harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pramana_contracts import Hedge, Skill

DEFAULT_RELIABILITY: dict[tuple[Skill, str], float] = {
    # Mean P(answer equals the true observable) for a direct, certain answer, by skill and probe
    # class. Each person's actual reliability per probe class is unknown and integrated out
    # (``reliability_model = "beta"``, docs/adr/0008); these are the prior means.
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
    reliability_model: Literal["beta", "fixed"] = "beta"
    """``beta``: each person's reliability per probe class is unknown, with a Beta prior around
    the mean above, integrated out by Gauss-Jacobi quadrature, so one person's answers share it
    (docs/adr/0008). ``fixed``: the reliability is exactly the mean (the earlier model)."""
    reliability_concentration: float = 20.0
    """``a + b`` of the Beta prior on ``(r - 0.5) / 0.5``. Larger means more certain."""
    quadrature_nodes: int = 8
    """Exact for up to ``2 * nodes - 1`` answers by one person in one probe class."""
    top_candidates: int = 8
    top_infeasible: int = 5
    planning_reliability: float = 0.95
    """Reliability assumed when valuing actions nobody present can perform (abstention report)."""
    presence_unverified_weight: float = 0.2
    """Weight of what someone reports seeing in a restricted place while their presence there
    is being checked, or after the check failed (PRODUCT.md: unverified presence 0.2)."""
    confirm_delta: float = 0.15
    """A single answer moving the leading decision's probability by more than this is
    decision-critical (PRODUCT.md, confirmation arbiter)."""
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
    parallel_min_bits: float = 0.05
    """A question asked alongside others in flight must add at least this many bits about the
    decision *given* their answers (conditional gain), so a second person is not asked
    something the first answer will already settle."""
    withdraw_bits: float = 0.01
    """A question still in flight is withdrawn when its answer could tell us less than this
    about the decision (after another person's answer made it pointless)."""

    def __post_init__(self) -> None:
        if not 0 < self.tau_lo <= self.tau_hi < 1:
            raise ValueError("require 0 < tau_lo <= tau_hi < 1")
        for key, r in self.reliability.items():
            if not 0.5 < r < 1:
                raise ValueError(f"reliability {key} must be in (0.5, 1)")
        if self.parallel_min_bits < 0 or self.withdraw_bits < 0:
            raise ValueError("require parallel_min_bits >= 0 and withdraw_bits >= 0")
        if self.reliability_concentration <= 0 or self.quadrature_nodes < 1:
            raise ValueError("require reliability_concentration > 0 and quadrature_nodes >= 1")
