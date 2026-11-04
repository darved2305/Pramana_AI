"""Shared builders for engine tests."""

from __future__ import annotations

from pramana_contracts import ParticipantSpec


def person(
    pid: str, roles: list[str], skill: str, loc: str, budget: int = 4, available: bool = True
) -> ParticipantSpec:
    return ParticipantSpec.model_validate(
        {
            "id": pid,
            "display_name": pid.removeprefix("p_").title(),
            "roles": roles,
            "skill": skill,
            "location_id": loc,
            "languages": {"stt_candidates": ["hi-IN", "en-IN"]},
            "question_budget": budget,
            "available": available,
        }
    )
