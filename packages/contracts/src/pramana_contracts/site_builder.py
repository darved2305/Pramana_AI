"""Describing a site, checking the model it generates, and publishing an immutable version.

A site description is the builder's input (places, roles, equipment, service points). It is
carried here as a JSON object because its schema lives with the domain builder; the core
validates it and returns every problem in readable form.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from .common import Identifier, Skill, StrictModel


class EquipmentFailureView(StrictModel):
    id: str
    label: str
    prior: float
    local: bool


class EquipmentCheckView(StrictModel):
    id: str
    label: str
    outcomes: list[str]
    skill: Skill


class EquipmentRepairView(StrictModel):
    id: str
    label: str
    trade: str


class EquipmentTypeView(StrictModel):
    id: str
    label: str
    failure_modes: list[EquipmentFailureView]
    checks: list[EquipmentCheckView]
    repairs: list[EquipmentRepairView]
    keywords: list[str]


class SiteTemplateView(StrictModel):
    id: str
    title: str
    kind: str
    summary: str
    description: dict[str, Any]


class SaveDraft(StrictModel):
    """Start or replace a draft from a template or from a full description."""

    template_id: Identifier | None = None
    description: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _one_source(self) -> SaveDraft:
        if (self.template_id is None) == (self.description is None):
            raise ValueError("send either template_id or description")
        return self


class HealthFinding(StrictModel):
    severity: Literal["error", "warning"]
    code: str
    message: str


class FaultHealth(StrictModel):
    hypothesis: str
    label: str
    decision: str
    reportable: bool
    episodes: int
    correct: int
    abstained: int
    wrong: int
    mean_questions: float | None
    mean_effort_s: float | None


class ModelHealth(StrictModel):
    ok: bool
    spec_sha256: str
    """The generated model this report judged; a later edit makes it stale."""
    people: int
    cast: Literal["directory", "one_per_role"]
    checked_at: datetime
    findings: list[HealthFinding]
    faults: list[FaultHealth]


class ModelCounts(StrictModel):
    places: int
    equipment: int
    checks: int
    decisions: int
    roles: int


class SiteModelDraft(StrictModel):
    id: str
    site_id: str
    version: int
    status: Literal["draft"] = "draft"
    description: dict[str, Any]
    spec_sha256: str
    counts: ModelCounts
    notes: list[str] = Field(default_factory=list)
    """What the builder could not generate and why."""
    health: ModelHealth | None = None
    """``None`` until checked, or when the draft changed after the last check."""
    created_at: datetime
