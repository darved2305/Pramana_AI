"""Participants: consenting people who can observe the site."""

from __future__ import annotations

from pydantic import Field, model_validator

from .common import Identifier, LanguageCode, Role, Skill, StrictModel, TemplateLanguage


class LanguageProfile(StrictModel):
    """How we speak to and listen to one participant.

    ``stt_candidates`` maps to the Prisma v3.0 ``language_code`` list (1-4 codes); one code
    forces the language, several act as a hint (docs.gnani.ai/api/STT/models/prisma-v3).
    """

    stt_candidates: list[LanguageCode] = Field(min_length=1, max_length=4)
    template_language: TemplateLanguage = "en"
    codemix: bool = False
    """Request Prisma ``format=codemix`` (English words kept in Latin script)."""

    @model_validator(mode="after")
    def _distinct(self) -> LanguageProfile:
        if len(set(self.stt_candidates)) != len(self.stt_candidates):
            raise ValueError("stt_candidates must be distinct")
        return self


class ParticipantSpec(StrictModel):
    """A participant registered on an investigation.

    Display names are synthetic (programme rule: synthetic data only).
    """

    id: Identifier
    display_name: str = Field(min_length=1, max_length=80)
    roles: list[Role] = Field(min_length=1)
    skill: Skill
    location_id: Identifier
    languages: LanguageProfile
    available: bool = True
    question_budget: int = Field(default=4, ge=0, le=20)
