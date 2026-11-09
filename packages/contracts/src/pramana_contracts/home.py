"""The workspace home: what to look at first, and why (PRODUCTION.md §7.5).

The core orders the modules with a pure rules function over the workspace's own data and the
person's roles, and says in plain words why each one is there. Pins and hides are the person's
saved preferences; a pinned module comes first, a hidden one is left out.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import StrictModel
from .domain_joins import JoinRequestView

HomeModuleId = Literal["approvals", "active", "decided", "setup", "sites", "recent"]


class SetupStep(StrictModel):
    id: Literal["workspace", "practice", "site", "people", "investigate"]
    label: str
    done: bool
    href: str
    """Where to go to do this step, relative to the workspace (``sites/…``)."""


class HomeInvestigation(StrictModel):
    id: str
    site_id: str | None
    status: str
    report_text: str
    decision_label: str | None = None
    decision_probability: float | None = None
    updated_at: str


class HomeSite(StrictModel):
    id: str
    name: str
    mode: Literal["sandbox", "live"]
    model_version: int | None
    draft: Literal["none", "unchecked", "healthy", "problems"]
    open_investigations: int


class HomeModule(StrictModel):
    id: HomeModuleId
    title: str
    reason: str
    """Why this module is shown here, in plain words ("2 repairs wait for your approval")."""
    pinned: bool = False
    investigations: list[HomeInvestigation] = Field(default_factory=list)
    sites: list[HomeSite] = Field(default_factory=list)
    steps: list[SetupStep] = Field(default_factory=list)


class WorkspaceHome(StrictModel):
    greeting_name: str
    modules: list[HomeModule]
    hidden: list[HomeModuleId] = Field(default_factory=list)
    join_requests: list[JoinRequestView] = Field(default_factory=list)
