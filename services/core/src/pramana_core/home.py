"""The workspace home: an ordered list of modules, each with the reason it is there.

``plan_home`` is a pure function of the workspace's facts and the person's roles and saved
layout, so the ordering is unit-tested without a database. ``load_facts`` reads those facts
for the current organization (row-level security and an explicit org filter both apply).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pramana_contracts import (
    HomeInvestigation,
    HomeModule,
    HomeSite,
    SetupStep,
    WorkspaceHome,
)

from . import ids
from .db import InvestigationRow, SiteModelRow, SiteRow
from .people import SitePersonRow
from .vault import ERASED_REPORT, SEALED, PersonVault

ACTIVE = {"investigating", "awaiting_approval", "acting", "verifying"}
CONCLUDED = {"verified", "not_verified", "closed", "abstained"}
RULE_ORDER = ("approvals", "active", "decided", "setup", "sites", "recent")


@dataclass(frozen=True)
class HomeFacts:
    display_name: str
    roles: frozenset[str]
    sites: list[HomeSite]
    awaiting_approval: list[HomeInvestigation] = field(default_factory=list)
    active: list[HomeInvestigation] = field(default_factory=list)
    decided: list[HomeInvestigation] = field(default_factory=list)
    recent: list[HomeInvestigation] = field(default_factory=list)
    practice_done: bool = False
    people: int = 0
    own_investigations: int = 0
    pins: tuple[str, ...] = ()
    hides: tuple[str, ...] = ()
    checklist_dismissed: bool = False


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def setup_steps(facts: HomeFacts) -> list[SetupStep]:
    own = [s for s in facts.sites if s.mode == "live"]
    published = any(s.model_version is not None for s in own)
    site_href = f"sites/{own[0].id}" if own else "sites"
    return [
        SetupStep(id="workspace", label="Create your workspace", done=True, href=""),
        SetupStep(
            id="practice",
            label="Run a practice investigation",
            done=facts.practice_done,
            href="investigations/new?practice=1",
        ),
        SetupStep(
            id="site", label="Describe your own site and publish it", done=published, href=site_href
        ),
        SetupStep(
            id="people", label="Add the people who can help", done=facts.people > 0, href="people"
        ),
        SetupStep(
            id="investigate",
            label="Investigate a problem on your site",
            done=facts.own_investigations > 0,
            href="investigations/new",
        ),
    ]


def plan_home(facts: HomeFacts) -> WorkspaceHome:
    operator = bool(facts.roles & {"owner", "admin", "operator"})
    candidates: dict[str, HomeModule] = {}

    if "approver" in facts.roles and facts.awaiting_approval:
        n = len(facts.awaiting_approval)
        candidates["approvals"] = HomeModule(
            id="approvals",
            title="Waiting for your approval",
            reason=f"{_plural(n, 'repair waits', 'repairs wait')} for your approval. "
            "Nothing is carried out until an approver says yes.",
            investigations=facts.awaiting_approval,
        )
    if facts.active:
        n = len(facts.active)
        candidates["active"] = HomeModule(
            id="active",
            title="Open investigations",
            reason=f"{_plural(n, 'investigation is', 'investigations are')} still asking people "
            "questions or checking a repair.",
            investigations=facts.active,
        )
    if operator and facts.decided:
        n = len(facts.decided)
        candidates["decided"] = HomeModule(
            id="decided",
            title="Diagnosed, ready to act",
            reason=f"{_plural(n, 'investigation has', 'investigations have')} reached a decision. "
            "Propose the repair so an approver can review it.",
            investigations=facts.decided,
        )
    steps = setup_steps(facts)
    remaining = [s for s in steps if not s.done]
    if remaining and not facts.checklist_dismissed:
        done = len(steps) - len(remaining)
        candidates["setup"] = HomeModule(
            id="setup",
            title="Set up Pramana",
            reason=f"{done} of {len(steps)} steps done. Next: {remaining[0].label.lower()}.",
            steps=steps,
        )
    if facts.sites:
        drafts = [s for s in facts.sites if s.draft in {"unchecked", "problems"}]
        if drafts:
            reason = f"{drafts[0].name} has a draft model " + (
                "with problems to fix." if drafts[0].draft == "problems" else "to check."
            )
        else:
            reason = f"{_plural(len(facts.sites), 'site', 'sites')} in this workspace."
        candidates["sites"] = HomeModule(
            id="sites", title="Your sites", reason=reason, sites=facts.sites
        )
    if facts.recent:
        last = facts.recent[0]
        outcome = last.decision_label or last.status.replace("_", " ")
        candidates["recent"] = HomeModule(
            id="recent",
            title="Recent outcomes",
            reason=f"Most recent: {outcome}.",
            investigations=facts.recent,
        )

    ordered_keys = [k for k in RULE_ORDER if k in candidates]
    pinned = [k for k in facts.pins if k in candidates]
    keys = pinned + [k for k in ordered_keys if k not in pinned]
    modules = [
        candidates[k].model_copy(update={"pinned": k in pinned})
        for k in keys
        if k not in facts.hides
    ]
    return WorkspaceHome(
        greeting_name=facts.display_name.split(" ")[0] if facts.display_name else "there",
        modules=modules,
        hidden=[k for k in facts.hides if k in candidates],
    )


def _decision_labels(spec: dict[str, Any] | None) -> dict[str, str]:
    return {d["id"]: d["label"] for d in (spec or {}).get("decision_classes", [])}


def _stored_report(row: InvestigationRow) -> str:
    return str((row.request.get("report") or {}).get("text", ""))


def _report_text(row: InvestigationRow, texts: dict[tuple[str, str, str], str]) -> str:
    stored = _stored_report(row)
    if stored != SEALED:
        return stored
    reporter = str((row.request.get("report") or {}).get("reporter_id", ""))
    return texts.get((row.id, "report", reporter), ERASED_REPORT)


async def load_facts(
    session: AsyncSession,
    org_id: Any,
    *,
    display_name: str,
    roles: frozenset[str],
    layout: dict[str, Any],
    vault: PersonVault | None = None,
) -> HomeFacts:
    sites = list(
        await session.scalars(
            select(SiteRow)
            .where(SiteRow.org_id == org_id, SiteRow.archived_at.is_(None))
            .order_by(SiteRow.mode.desc(), SiteRow.created_at.desc(), SiteRow.id.desc())
            .limit(100)
        )
    )
    site_ids = [site.id for site in sites]
    current_model_ids = [site.current_model_id for site in sites if site.current_model_id]
    models = {
        model.id: model
        for model in await session.scalars(
            select(SiteModelRow).where(
                SiteModelRow.org_id == org_id,
                SiteModelRow.id.in_(current_model_ids),
            )
        )
    }
    draft_rows = list(
        await session.scalars(
            select(SiteModelRow)
            .where(
                SiteModelRow.org_id == org_id,
                SiteModelRow.site_id.in_(site_ids),
                SiteModelRow.status == "draft",
            )
            .order_by(SiteModelRow.site_id, SiteModelRow.created_at.desc(), SiteModelRow.id.desc())
            .limit(100)
        )
    )
    drafts: dict[uuid.UUID, SiteModelRow] = {}
    for model in draft_rows:
        drafts.setdefault(model.site_id, model)
        models[model.id] = model
    rows = list(
        await session.scalars(
            select(InvestigationRow)
            .where(InvestigationRow.org_id == org_id)
            .order_by(InvestigationRow.updated_at.desc(), InvestigationRow.id.desc())
            .limit(200)
        )
    )
    sealed = [r.id for r in rows if _stored_report(r) == SEALED]
    texts = await vault.texts(session, org_id, sealed) if vault is not None else {}
    open_by_site: dict[Any, int] = {}
    for r in rows:
        if r.status in ACTIVE | {"decided"}:
            open_by_site[r.site_id] = open_by_site.get(r.site_id, 0) + 1

    def draft_state(site: SiteRow) -> str:
        d = drafts.get(site.id)
        if d is None:
            return "none"
        health = (d.validation or {}).get("health")
        if not health or health.get("spec_sha256") != d.spec_sha256.hex():
            return "unchecked"
        return "healthy" if health.get("ok") else "problems"

    home_sites = [
        HomeSite(
            id=ids.encode("site", s.id),
            name=s.name,
            mode="sandbox" if s.mode == "sandbox" else "live",
            model_version=models[s.current_model_id].version
            if s.current_model_id in models
            else None,
            draft=draft_state(s),
            open_investigations=open_by_site.get(s.id, 0),
        )
        for s in sites
    ]

    def view(r: InvestigationRow) -> HomeInvestigation:
        outcome = r.outcome or {}
        model = models.get(r.site_model_id) if r.site_model_id else None
        decision = outcome.get("decision_class")
        return HomeInvestigation(
            id=r.id,
            site_id=ids.encode("site", r.site_id) if r.site_id else None,
            status=r.status,
            report_text=_report_text(r, texts)[:200],
            decision_label=_decision_labels(model.spec if model else None).get(decision)
            if decision
            else None,
            decision_probability=outcome.get("decision_probability"),
            updated_at=r.updated_at.isoformat(),
        )

    sandbox_ids = {s.id for s in sites if s.mode == "sandbox"}
    people = await session.scalar(
        select(func.count()).select_from(SitePersonRow).where(SitePersonRow.org_id == org_id)
    )
    return HomeFacts(
        display_name=display_name,
        roles=roles,
        sites=home_sites,
        awaiting_approval=[view(r) for r in rows if r.status == "awaiting_approval"][:5],
        active=[view(r) for r in rows if r.status in ACTIVE - {"awaiting_approval"}][:5],
        decided=[view(r) for r in rows if r.status == "decided"][:5],
        recent=[view(r) for r in rows if r.status in CONCLUDED][:5],
        practice_done=any(
            r.site_id in sandbox_ids and r.status in CONCLUDED | {"decided"} for r in rows
        ),
        people=int(people or 0),
        own_investigations=sum(1 for r in rows if r.site_id not in sandbox_ids),
        pins=tuple(layout.get("pins", [])),
        hides=tuple(layout.get("hides", [])),
        checklist_dismissed=bool(layout.get("checklist_dismissed", False)),
    )
