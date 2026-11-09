"""People per site: who can be asked, where they usually are, which roles they hold.

Each person is checked against the site's own model (its role catalogue and places): the
published version, or the open draft before the first publish. Updates use the stored version
as a precondition, so two editors cannot silently overwrite each other.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import (
    DateTime,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    String,
    bindparam,
    func,
    inspect,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from pramana_contracts import (
    ConsentRecord,
    ParticipantPatch,
    ParticipantSpec,
    RecordConsent,
    SitePerson,
)
from pramana_domain import DomainPack
from pramana_domain.spec_storage import load_spec

from . import ids
from .account_rows import IdempotencyRow
from .auth.service import Principal
from .cursors import CursorCodec, like_escape
from .db import AuditLogRow, Base, Database, SiteModelRow, SiteRow, current_org
from .errors import ApiError, not_found
from .vault import SEALED, PersonKeyRow, PersonRef, PersonVault

_ERASED_RESPONSE = json.dumps(
    {"error": {"code": "PERSON_ERASED", "message": "this response named someone since erased"}}
).encode()


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
    display_name_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConsentRow(Base):
    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    person_id: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(32))
    notice_version: Mapped[str] = mapped_column(String(32))
    language: Mapped[str] = mapped_column(String(16))
    channel: Mapped[str] = mapped_column(String(16))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB)


def consent_view(row: ConsentRow) -> ConsentRecord:
    return ConsentRecord.model_validate(
        {
            "id": ids.encode("consent", row.id),
            "purpose": row.purpose,
            "notice_version": row.notice_version,
            "language": row.language,
            "channel": row.channel,
            "evidence": row.evidence,
            "granted_at": row.granted_at,
            "withdrawn_at": row.withdrawn_at,
        }
    )


def _full_spec(row: SitePersonRow) -> ParticipantSpec:
    """The stored spec with the real name, which was put on the row when it was read."""
    name = inspect(row).info.get("name")
    spec = ParticipantSpec.model_validate(row.spec)
    return spec.model_copy(update={"display_name": name}) if name else spec


def person_view(row: SitePersonRow) -> SitePerson:
    return SitePerson(
        site_id=ids.encode("site", row.site_id),
        person=_full_spec(row),
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
    def __init__(self, db: Database, vault: PersonVault) -> None:
        self.db = db
        self.vault = vault

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

    async def _reveal(self, session: AsyncSession, rows: list[SitePersonRow]) -> None:
        if not rows:
            return
        keys = await self.vault.site_keys(session, rows[0].org_id, rows[0].site_id)
        for row in rows:
            key = keys.get(row.id)
            if row.display_name_enc is not None and key is not None:
                ref = PersonRef(row.org_id, row.site_id, row.id)
                inspect(row).info["name"] = self.vault.decrypt(
                    key, ref, "display_name", row.display_name_enc
                )

    async def _seal_name(self, session: AsyncSession, row: SitePersonRow, name: str) -> None:
        ref = PersonRef(row.org_id, row.site_id, row.id)
        key = await self.vault.data_key(session, ref)
        if key is None:
            raise ApiError(409, "PERSON_ERASED", "this person was erased; use a new id")
        row.display_name_enc = self.vault.encrypt(key, ref, "display_name", name)
        row.spec = {**row.spec, "display_name": SEALED}
        inspect(row).info["name"] = name

    async def listing(self, site_id: uuid.UUID) -> list[SitePersonRow]:
        async with self.db.read() as session:
            site = await self._site(session, site_id)
            rows = list(
                await session.scalars(
                    select(SitePersonRow)
                    .where(SitePersonRow.org_id == site.org_id, SitePersonRow.site_id == site.id)
                    .order_by(SitePersonRow.id)
                )
            )
            await self._reveal(session, rows)
            return rows

    async def require_site(self, site_id: uuid.UUID) -> None:
        async with self.db.read() as session:
            await self._site(session, site_id)

    async def listing_page(
        self,
        site_id: uuid.UUID,
        *,
        limit: int,
        cursor: str | None,
        q: str | None,
        codec: CursorCodec,
    ) -> tuple[list[SitePersonRow], str | None]:
        org_id = self._org()
        needle = q.strip() if q else ""
        filters = {"q": needle}
        scope = f"people:{site_id}"
        sort = codec.decode(cursor, scope=scope, org_id=str(org_id), filters=filters)
        query = select(SitePersonRow).where(
            SitePersonRow.org_id == org_id, SitePersonRow.site_id == site_id
        )
        if needle:
            query = query.where(SitePersonRow.id.ilike(f"%{like_escape(needle)}%", escape="\\"))
        if sort is not None:
            try:
                after_created = datetime.fromisoformat(str(sort[0]))
            except ValueError as exc:
                raise ApiError(400, "CURSOR_INVALID", "Restart from the first page.") from exc
            query = query.where(
                tuple_(SitePersonRow.created_at, SitePersonRow.id)
                < tuple_(after_created, str(sort[1]))
            )
        async with self.db.read() as session:
            await self._site(session, site_id)
            rows = list(
                await session.scalars(
                    query.order_by(SitePersonRow.created_at.desc(), SitePersonRow.id.desc()).limit(
                        limit + 1
                    )
                )
            )
            has_more = len(rows) > limit
            rows = rows[:limit]
            await self._reveal(session, rows)
        next_cursor = (
            codec.encode(
                scope=scope,
                org_id=str(org_id),
                filters=filters,
                sort=[rows[-1].created_at.isoformat(), rows[-1].id],
            )
            if has_more and rows
            else None
        )
        return rows, next_cursor

    async def specs(self, site_id: uuid.UUID) -> list[ParticipantSpec]:
        return [_full_spec(r) for r in await self.listing(site_id)]

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
            await self._seal_name(session, row, spec.display_name)
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
            changes = patch.model_dump(mode="json", exclude_unset=True)
            merged_fields = set(changes)
            merged = {**row.spec, **changes}
            try:
                spec = ParticipantSpec.model_validate(merged)
            except ValidationError as exc:
                raise ApiError(422, "INVALID_PERSON", str(exc.errors()[0]["msg"])) from exc
            check_fits(await self.model_for(session, site), spec)
            await self._reveal(session, [row])
            name = spec.display_name if "display_name" in merged_fields else None
            row.spec = spec.model_dump(mode="json")
            await self._seal_name(
                session, row, name or inspect(row).info.get("name") or spec.display_name
            )
            row.version += 1
            row.updated_at = datetime.now(UTC)
            await session.flush()
            return row

    async def remove(self, site_id: uuid.UUID, person_id: str) -> None:
        async with self.db.transaction() as session:
            site = await self._site(session, site_id)
            await session.delete(await self._locked(session, site, person_id))

    async def erase(self, site_id: uuid.UUID, person_id: str, principal: Principal) -> None:
        """Delete this person's key and directory entry. Their investigations stay replayable."""
        async with self.db.transaction() as session:
            site = await self._site(session, site_id)
            ref = PersonRef(site.org_id, site.id, person_id)
            row = await session.get(
                SitePersonRow, (site.org_id, site.id, person_id), with_for_update=True
            )
            known = await session.get(PersonKeyRow, (site.org_id, site.id, person_id))
            if row is None and known is None:
                raise not_found("person")
            await self.vault.erase(session, ref)
            if row is not None:
                await session.delete(row)
            # Saved responses repeat names and reports. Keep the claim, so an old retry still
            # cannot run twice, but drop the words.
            await session.execute(
                update(IdempotencyRow)
                .where(
                    IdempotencyRow.org_id == site.org_id,
                    IdempotencyRow.response_body.is_not(None),
                    text("position(:person in response_body) > 0").bindparams(
                        bindparam("person", json.dumps(person_id).encode(), type_=LargeBinary)
                    ),
                )
                .values(response_status=410, response_body=_ERASED_RESPONSE, response_headers={})
            )
            session.add(
                AuditLogRow(
                    id=ids.uuid7(),
                    org_id=site.org_id,
                    actor_kind="user",
                    actor_id=principal.id,
                    action="person.erased",
                    target_kind="person",
                    target_id=person_id,
                    details={"site_id": ids.encode("site", site.id)},
                )
            )

    async def consents(self, site_id: uuid.UUID, person_id: str) -> list[ConsentRow]:
        async with self.db.read() as session:
            site = await self._site(session, site_id)
            return list(
                await session.scalars(
                    select(ConsentRow)
                    .where(
                        ConsentRow.org_id == site.org_id,
                        ConsentRow.site_id == site.id,
                        ConsentRow.person_id == person_id,
                    )
                    .order_by(ConsentRow.granted_at.desc())
                )
            )

    async def consent_page(
        self,
        site_id: uuid.UUID,
        person_id: str,
        *,
        limit: int,
        cursor: str | None,
        codec: CursorCodec,
    ) -> tuple[list[ConsentRow], str | None]:
        org_id = self._org()
        filters: dict[str, object] = {"person_id": person_id}
        scope = f"consents:{site_id}"
        sort = codec.decode(cursor, scope=scope, org_id=str(org_id), filters=filters)
        query = select(ConsentRow).where(
            ConsentRow.org_id == org_id,
            ConsentRow.site_id == site_id,
            ConsentRow.person_id == person_id,
        )
        if sort is not None:
            try:
                after_created = datetime.fromisoformat(str(sort[0]))
                after_id = uuid.UUID(str(sort[1]))
            except ValueError as exc:
                raise ApiError(400, "CURSOR_INVALID", "Restart from the first page.") from exc
            query = query.where(
                tuple_(ConsentRow.granted_at, ConsentRow.id) < tuple_(after_created, after_id)
            )
        async with self.db.read() as session:
            await self._site(session, site_id)
            rows = list(
                await session.scalars(
                    query.order_by(ConsentRow.granted_at.desc(), ConsentRow.id.desc()).limit(
                        limit + 1
                    )
                )
            )
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            codec.encode(
                scope=scope,
                org_id=str(org_id),
                filters=filters,
                sort=[rows[-1].granted_at.isoformat(), str(rows[-1].id)],
            )
            if has_more and rows
            else None
        )
        return rows, next_cursor

    async def grant_consent(
        self, site_id: uuid.UUID, person_id: str, body: RecordConsent, principal: Principal
    ) -> ConsentRow:
        async with self.db.transaction() as session:
            site = await self._site(session, site_id)
            await self._locked(session, site, person_id)
            now = datetime.now(UTC)
            active = await self._active(session, site, person_id, body.purpose)
            if active is not None:
                active.withdrawn_at = now  # the newest notice replaces the earlier one
                await session.flush()
            row = ConsentRow(
                id=ids.uuid7(),
                org_id=site.org_id,
                site_id=site.id,
                person_id=person_id,
                purpose=body.purpose,
                notice_version=body.notice_version,
                language=body.language,
                channel=body.channel,
                granted_at=now,
                evidence=body.evidence,
            )
            session.add(row)
            session.add(
                self._consent_audit(site, person_id, principal, "consent.granted", body.purpose)
            )
            await session.flush()
            return row

    async def withdraw_consent(
        self, site_id: uuid.UUID, person_id: str, purpose: str, principal: Principal
    ) -> None:
        async with self.db.transaction() as session:
            site = await self._site(session, site_id)
            active = await self._active(session, site, person_id, purpose)
            if active is None:
                return
            active.withdrawn_at = datetime.now(UTC)
            session.add(
                self._consent_audit(site, person_id, principal, "consent.withdrawn", purpose)
            )

    @staticmethod
    async def _active(
        session: AsyncSession, site: SiteRow, person_id: str, purpose: str
    ) -> ConsentRow | None:
        return await session.scalar(
            select(ConsentRow)
            .where(
                ConsentRow.org_id == site.org_id,
                ConsentRow.site_id == site.id,
                ConsentRow.person_id == person_id,
                ConsentRow.purpose == purpose,
                ConsentRow.withdrawn_at.is_(None),
            )
            .with_for_update()
        )

    @staticmethod
    def _consent_audit(
        site: SiteRow, person_id: str, principal: Principal, action: str, purpose: str
    ) -> AuditLogRow:
        return AuditLogRow(
            id=ids.uuid7(),
            org_id=site.org_id,
            actor_kind="user",
            actor_id=principal.id,
            action=action,
            target_kind="person",
            target_id=person_id,
            details={"site_id": ids.encode("site", site.id), "purpose": purpose},
        )
