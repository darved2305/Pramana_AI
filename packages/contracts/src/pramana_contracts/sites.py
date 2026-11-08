"""Read-only saved site model contracts. No simulator state or hidden fault is included."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from .common import StrictModel


class SiteModelSummary(StrictModel):
    id: str
    org_id: str
    site_id: str
    version: int
    status: Literal["published", "retired"]
    spec_sha256: str
    created_at: datetime
    published_at: datetime | None


class SiteModelDocument(SiteModelSummary):
    spec: dict[str, Any]
    description: dict[str, Any] | None = None
    """The site description it was generated from, when made with the builder."""
