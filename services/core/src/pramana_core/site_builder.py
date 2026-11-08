"""Site model drafts: describe a site, generate its model, check it, publish an immutable version.

One draft per site at a time. Saving regenerates the model from the description; the model
health check judges the generated model against the site's people (or one person per role
when none are entered yet) and is stored with the draft. Publishing requires a passing check
of exactly the current model, retires the previous version and points the site at the new one.
Published versions never change (database trigger); investigations pin the version they used.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pramana_contracts import (
    ModelCounts,
    ModelHealth,
    ParticipantSpec,
    SaveDraft,
    SiteModelDraft,
    SiteModelSummary,
)
from pramana_domain import DomainPack
from pramana_domain.builder import SiteDescription, build
from pramana_domain.catalog import template
from pramana_domain.spec_storage import load_spec, spec_digest
from pramana_engine.health import check, default_cast

from . import ids
from .db import Database, SiteModelRow, SiteRow, current_org, current_user
from .errors import ApiError, not_found
from .people import SitePeople

HEALTH_EPISODES = 12


def _org() -> Any:
    org = current_org.get()
    if org is None:
        raise not_found("site")
    return org


def description_errors(exc: ValidationError) -> list[str]:
    """Readable problems, one per line, from the builder's or the model's validators."""
    out: list[str] = []
    for err in exc.errors():
        msg = str(err.get("msg", ""))
        if "invalid site description:" in msg or "invalid domain pack:" in msg:
            out.extend(line.strip(" -") for line in msg.splitlines()[1:] if line.strip())
        else:
            where = ".".join(str(p) for p in err.get("loc", ()))
            out.append(f"{where}: {msg}" if where else msg)
    return out


def _generate(description: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    try:
        result = build(SiteDescription.model_validate(description))
    except ValidationError as exc:
        raise ApiError(
            422,
            "SITE_DESCRIPTION_INVALID",
            "the site description has problems to fix",
            details={"problems": description_errors(exc)},
        ) from exc
    except ValueError as exc:  # raised by the generated model's own validation
        raise ApiError(
            422,
            "SITE_DESCRIPTION_INVALID",
            "the site description has problems to fix",
            details={"problems": [str(exc)]},
        ) from exc
    return result.spec, result.notes


def _counts(pack: DomainPack) -> ModelCounts:
    return ModelCounts(
        places=len(pack.locations),
        equipment=len(pack.components),
        checks=sum(len(p.observes) for p in pack.probes),
        decisions=len(pack.decision_classes),
        roles=len(pack.role_catalogue),
    )


def draft_etag(row: SiteModelRow) -> str:
    return f'"{row.spec_sha256.hex()}"'


def draft_view(row: SiteModelRow) -> SiteModelDraft:
    source = row.source or {}
    health = (row.validation or {}).get("health")
    if health is not None and health.get("spec_sha256") != row.spec_sha256.hex():
        health = None  # judged an earlier model
    return SiteModelDraft(
        id=ids.encode("model", row.id),
        site_id=ids.encode("site", row.site_id),
        version=row.version,
        description=source.get("description", {}),
        spec_sha256=row.spec_sha256.hex(),
        counts=_counts(load_spec(row.spec)),
        notes=list(source.get("notes", [])),
        health=ModelHealth.model_validate(health) if health else None,
        created_at=row.created_at,
    )


class SiteBuilder:
    def __init__(self, db: Database, people: SitePeople | None = None) -> None:
        self.db = db
        self.people = people

    async def _site(self, session: AsyncSession, site_id: Any, *, lock: bool = False) -> SiteRow:
        stmt = select(SiteRow).where(
            SiteRow.id == site_id, SiteRow.org_id == _org(), SiteRow.archived_at.is_(None)
        )
        site = await session.scalar(stmt.with_for_update() if lock else stmt)
        if site is None:
            raise not_found("site")
        if site.mode == "sandbox":
            raise ApiError(409, "SANDBOX_READ_ONLY", "the practice site cannot be edited")
        return site

    @staticmethod
    async def _draft(
        session: AsyncSession, site: SiteRow, *, lock: bool = False
    ) -> SiteModelRow | None:
        stmt = select(SiteModelRow).where(
            SiteModelRow.org_id == site.org_id,
            SiteModelRow.site_id == site.id,
            SiteModelRow.status == "draft",
        )
        return await session.scalar(stmt.with_for_update() if lock else stmt)

    async def get(self, site_id: Any) -> SiteModelRow:
        async with self.db.read() as session:
            site = await self._site(session, site_id)
            row = await self._draft(session, site)
        if row is None:
            raise not_found("draft")
        return row

    async def save(self, site_id: Any, body: SaveDraft, if_match: str | None) -> SiteModelRow:
        if body.template_id is not None:
            description = template(body.template_id)
            if description is None:
                raise ApiError(422, "UNKNOWN_TEMPLATE", f"there is no template {body.template_id}")
        else:
            assert body.description is not None
            description = body.description
        spec, notes = await asyncio.to_thread(_generate, description)
        digest = spec_digest(spec)
        async with self.db.transaction() as session:
            site = await self._site(session, site_id, lock=True)
            row = await self._draft(session, site, lock=True)
            source = {"description": description, "notes": notes}
            if row is None:
                if if_match is not None:
                    raise ApiError(412, "DRAFT_CHANGED", "this draft was published or discarded")
                latest = await session.scalar(
                    select(func.max(SiteModelRow.version)).where(
                        SiteModelRow.org_id == site.org_id, SiteModelRow.site_id == site.id
                    )
                )
                row = SiteModelRow(
                    id=ids.uuid7(),
                    org_id=site.org_id,
                    site_id=site.id,
                    version=(latest or 0) + 1,
                    status="draft",
                    spec=spec,
                    spec_sha256=digest,
                    source=source,
                    validation=None,
                    created_by=current_user.get(),
                )
                session.add(row)
            else:
                if if_match is None:
                    raise ApiError(
                        428, "PRECONDITION_REQUIRED", "send the draft version you are editing"
                    )
                if if_match != draft_etag(row):
                    raise ApiError(
                        412, "DRAFT_CHANGED", "someone else changed this draft; reload it"
                    )
                row.spec, row.spec_sha256, row.source = spec, digest, source
                if (row.validation or {}).get("health", {}).get("spec_sha256") != digest.hex():
                    row.validation = None  # the stored check judged a different model
            await session.flush()
            return row

    async def discard(self, site_id: Any, model_id: Any) -> None:
        async with self.db.transaction() as session:
            site = await self._site(session, site_id, lock=True)
            row = await self._draft(session, site, lock=True)
            if row is None or row.id != model_id:
                raise not_found("draft")
            await session.delete(row)

    async def health(
        self, site_id: Any, model_id: Any, people: list[ParticipantSpec] | None
    ) -> SiteModelRow:
        row = await self.get(site_id)
        if row.id != model_id:
            raise not_found("draft")
        pack = load_spec(row.spec)
        if people is None and self.people is not None:
            people = await self.people.specs(site_id) or None
        cast = people or default_cast(pack)
        for person in cast:
            unknown = set(map(str, person.roles)) - set(pack.role_catalogue)
            if unknown or person.location_id not in pack.location_by_id:
                raise ApiError(
                    422, "PERSON_NOT_ON_SITE", f"{person.id} does not fit this site's model"
                )
        report = await asyncio.to_thread(check, pack, cast, episodes=HEALTH_EPISODES)
        result = report.as_dict()
        health = ModelHealth.model_validate(
            {
                "ok": result["ok"],
                "findings": result["findings"],
                "faults": result["faults"],
                "spec_sha256": row.spec_sha256.hex(),
                "people": len(cast),
                "cast": "directory" if people else "one_per_role",
                "checked_at": datetime.now(UTC),
            }
        ).model_dump(mode="json")
        async with self.db.transaction() as session:
            site = await self._site(session, site_id, lock=True)
            current = await self._draft(session, site, lock=True)
            if current is None or current.id != row.id or current.spec_sha256 != row.spec_sha256:
                raise ApiError(409, "DRAFT_CHANGED", "the draft changed while it was checked")
            current.validation = {"health": health}
            await session.flush()
            return current

    async def publish(self, site_id: Any, model_id: Any) -> SiteModelRow:
        async with self.db.transaction() as session:
            site = await self._site(session, site_id, lock=True)
            row = await self._draft(session, site, lock=True)
            if row is None or row.id != model_id:
                raise not_found("draft")
            health = (row.validation or {}).get("health")
            if health is None or health.get("spec_sha256") != row.spec_sha256.hex():
                raise ApiError(409, "HEALTH_CHECK_REQUIRED", "check this model before publishing")
            if not health.get("ok"):
                raise ApiError(
                    409, "HEALTH_CHECK_FAILED", "fix the problems the health check found first"
                )
            now = datetime.now(UTC)
            if site.current_model_id is not None:
                previous = await session.scalar(
                    select(SiteModelRow).where(
                        SiteModelRow.org_id == site.org_id,
                        SiteModelRow.id == site.current_model_id,
                    )
                )
                if previous is not None and previous.status == "published":
                    previous.status = "retired"
            row.status, row.published_at = "published", now
            await session.flush()
            site.current_model_id = row.id
            await session.flush()
            return row


def summary(row: SiteModelRow) -> SiteModelSummary:
    return SiteModelSummary.model_validate(
        {
            "id": ids.encode("model", row.id),
            "org_id": ids.encode("org", row.org_id),
            "site_id": ids.encode("site", row.site_id),
            "version": row.version,
            "status": row.status,
            "spec_sha256": row.spec_sha256.hex(),
            "created_at": row.created_at,
            "published_at": row.published_at,
        }
    )
