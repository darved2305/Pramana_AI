"""Simulator-visible contracts.

The simulator's private truth model never appears here. ``FaultSpec`` describes the *shape* of a
fault; its value for a scenario is only disclosed by an authorized reveal after the
investigation has closed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import Identifier, StrictModel


class Fault(StrictModel):
    component_id: Identifier
    mode: Identifier


class FaultSpec(StrictModel):
    faults: list[Fault] = Field(max_length=3)
    """An empty list means nothing is broken (the report was a user-side issue)."""


class SimParticipant(StrictModel):
    id: Identifier
    location_id: Identifier
    roles: list[str] = Field(min_length=1)


class CreateScenario(StrictModel):
    pack_id: Identifier
    seed: int = Field(ge=0, le=2**31 - 1)
    fault: Literal["random"] | FaultSpec = "random"
    participants: list[SimParticipant] = Field(min_length=1, max_length=12)


class ScenarioCreated(StrictModel):
    scenario_id: str
    commitment: str
    """sha256(scenario_id | canonical fault spec | salt), hex. Published before the run."""


class ViewItem(StrictModel):
    """One thing a participant can perceive at their current location."""

    probe_id: Identifier
    label: str
    value: str


class ParticipantView(StrictModel):
    scenario_id: str
    participant_id: Identifier
    location_id: Identifier
    location_label: str
    items: list[ViewItem]
    reachable_locations: list[Identifier]


class MoveRequest(StrictModel):
    to: Identifier


class MoveResult(StrictModel):
    location_id: Identifier
    walk_s: int


class ObserveRequest(StrictModel):
    probe_id: Identifier


class ObserveResult(StrictModel):
    probe_id: Identifier
    location_id: Identifier
    value: str


class ActRequest(StrictModel):
    action: Identifier
    target: Identifier
    capability: str = Field(min_length=10, max_length=2000)


class ActResult(StrictModel):
    """Confirms the action was carried out. Deliberately says nothing about whether it fixed
    anything: that is only visible through what people observe afterwards."""

    action: Identifier
    target: Identifier
    performed: bool


class RevealResult(StrictModel):
    scenario_id: str
    fault_spec: FaultSpec
    salt: str
    commitment: str
    commitment_verified: bool
