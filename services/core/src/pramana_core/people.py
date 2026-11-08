"""People per site: who can be asked, where they usually are, which roles they hold.

Each person is checked against the site's own model (its role catalogue and places): the
published version, or the open draft before the first publish. Updates use the stored version
as a precondition, so two editors cannot silently overwrite each other.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import DateTime, ForeignKeyConstraint, Integer, String, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from pramana_contracts import ParticipantPatch, ParticipantSpec, SitePerson
from pramana_domain import DomainPack
from pramana_domain.spec_storage import load_spec

from . import ids
from .db import Base, Database, SiteModelRow, SiteRow, current_org
from .errors import ApiError, not_found


class SitePersonRow(Base):
    __tablename__ = "site_people"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "site_id"], ["sites.org_id", "sites.id"], name="site_people_site_fk"
        ),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def person_view(row: SitePersonRow) -> SitePerson:
    return SitePerson(
        site_id=ids.encode("site", row.site_id),
        person=ParticipantSpec.model_validate(row.spec),
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def person_etag(row: SitePersonRow) -> str:
    return f'"{row.version}"'


def check_fits(pack: DomainPack, spec: ParticipantSpec) -> None:
    if spec.location_id not in pack.location_by_id:
        raise ApiError(422, "UNKNOWN_LOCATION", f"this site has no place {spec.location_id}")
    unknown = sorted(set(map(str, spec.roles)) - set(pack.role_catalogue))
    if unknown:
        raise ApiError(422, "UNKNOWN_ROLE", f"this site has no role {unknown[0]}")


class SitePeople:
    def __init__(self, db: Database) -> None:
        self.db = db

    @staticmethod
    def _org() -> uuid.UUID:
        org = current_org.get()
        if org is None:
            raise not_found("site")
        return org

    async def _site(self, session: AsyncSession, site_id: uuid.UUID) -> SiteRow:
        site = await session.scalar(
            select(SiteRow).where(
                SiteRow.id == site_id, SiteRow.org_id == self._org(), SiteRow.archived_at.is_(None)
            )
        )
        if site is None:
            raise not_found("site")
        return site

    async def model_for(self, session: AsyncSession, site: SiteRow) -> DomainPack:
        """The model people are checked against: published, else the open draft."""
        row: SiteModelRow | None = None
        if site.current_model_id is not None:
            row = await session.scalar(
                select(SiteModelRow).where(
                    SiteModelRow.org_id == site.org_id, SiteModelRow.id == site.current_model_id
                )
            )
        if row is None:
            row = await session.scalar(
                select(SiteModelRow).where(
                    SiteModelRow.org_id == site.org_id,
                    SiteModelRow.site_id == site.id,
                    SiteModelRow.status == "draft",
                )
            )
        if row is None:
            raise ApiError(
                409, "SITE_MODEL_REQUIRED", "describe this site first, so people can be placed"
            )
        return load_spec(row.spec)

    async def listing(self, site_id: uuid.UUID) -> list[SitePersonRow]:
        async with self.db.read() as session:
            site = await self._site(session, site_id)
            return list(
                await session.scalars(
                    select(SitePersonRow)
                    .where(SitePersonRow.org_id == site.org_id, SitePersonRow.site_id == site.id)
                    .order_by(SitePersonRow.id)
                )
            )

    async def specs(self, site_id: uuid.UUID) -> list[ParticipantSpec]:
        return [ParticipantSpec.model_validate(r.spec) for r in await self.listing(site_id)]

    async def add(self, site_id: uuid.UUID, spec: ParticipantSpec) -> SitePersonRow:
        async with self.db.transaction() as session:
            site = await self._site(session, site_id)
            check_fits(await self.model_for(session, site), spec)
            existing = await session.get(SitePersonRow, (site.org_id, site.id, spec.id))
            if existing is not None:
                raise ApiError(409, "PERSON_EXISTS", f"{spec.id} is already listed for this site")
            now = datetime.now(UTC)
            row = SitePersonRow(
                org_id=site.org_id,
                site_id=site.id,
                id=spec.id,
                spec=spec.model_dump(mode="json"),
                version=1,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            await session.flush()
            return row

    async def _locked(self, session: AsyncSession, site: SiteRow, person_id: str) -> SitePersonRow:
        row = await session.get(
            SitePersonRow, (site.org_id, site.id, person_id), with_for_update=True
        )
        if row is None:
            raise not_found("person")
        return row

    async def update(
        self, site_id: uuid.UUID, person_id: str, patch: ParticipantPatch, if_match: str | None
    ) -> SitePersonRow:
        async with self.db.transaction() as session:
            site = await self._site(session, site_id)
            row = await self._locked(session, site, person_id)
            if if_match is None:
                raise ApiError(428, "PRECONDITION_REQUIRED", "send the version you are editing")
            if if_match != person_etag(row):
                raise ApiError(412, "PERSON_CHANGED", "someone else changed this person; reload")
            merged = {**row.spec, **patch.model_dump(mode="json", exclude_unset=True)}
            try:
                spec = ParticipantSpec.model_validate(merged)
            except ValidationError as exc:
                raise ApiError(422, "INVALID_PERSON", str(exc.errors()[0]["msg"])) from exc
            check_fits(await self.model_for(session, site), spec)
            row.spec = spec.model_dump(mode="json")
            row.version += 1
            row.updated_at = datetime.now(UTC)
            await session.flush()
            return row

    async def remove(self, site_id: uuid.UUID, person_id: str) -> None:
        async with self.db.transaction() as session:
            site = await self._site(session, site_id)
            await session.delete(await self._locked(session, site, person_id))
