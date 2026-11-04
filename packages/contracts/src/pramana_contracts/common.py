"""Primitive types shared by every contract."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

CONTRACTS_VERSION = "1.0.0"

Identifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")]
"""Stable machine identifier (participants, probes, locations, components)."""

Probability = Annotated[float, Field(ge=0.0, le=1.0)]

LanguageCode = Literal[
    "en-IN", "hi-IN", "mr-IN", "bn-IN", "gu-IN", "kn-IN", "ml-IN", "pa-IN", "ta-IN", "te-IN"
]
"""BCP-47 codes accepted by Gnani Prisma for STT (docs.gnani.ai/api/STT/languages)."""

TemplateLanguage = Literal["en", "hi", "mr", "hi-en"]
"""Languages our question templates are written in. ``hi-en`` is the Hinglish register."""


class StrictModel(BaseModel):
    """Base for all contracts: unknown fields are errors, instances are immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Role(StrEnum):
    STUDENT = "student"
    GUARD = "guard"
    ELECTRICIAN = "electrician"
    IT_TECH = "it_tech"
    HOUSEKEEPING = "housekeeping"


class Skill(StrEnum):
    LAY = "lay"
    ACCESS = "access"
    TECHNICIAN = "technician"


class Hedge(StrEnum):
    CERTAIN = "certain"
    PROBABLE = "probable"
    UNSURE = "unsure"


class Directness(StrEnum):
    DIRECT = "direct"
    HEARSAY = "hearsay"
    ASSUMPTION = "assumption"
    """The participant stated a conclusion about a cause. Never used as evidence."""


class Modality(StrEnum):
    TEXT = "text"
    VOICE = "voice"
    TAP = "tap"
    SIMULATED = "simulated"


UNKNOWN_OUTCOME = "unknown"
"""Outcome value meaning the answer could not be mapped to the probe's outcome set."""
