"""Owner export, reversible workspace deletion, and the 30-day personal-data purge."""

from __future__ import annotations

import json
import tempfile
import uuid
import zipfile
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, null, select, text, tuple_, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from pramana_contracts import DeleteOrganization, OrganizationDeletion

from . import ids
from .account_rows import IdempotencyRow, InvitationRow, OnboardingRow, PreferenceRow
from .db import (
    ApprovalRow,
    AuditLogRow,
    Database,
    EventRow,
    InvestigationRow,
    MembershipRow,
    ObservationRow,
    OrganizationRow,
    QuestionRow,
    SiteModelRow,
    SiteRow,
    UserRow,
    acting_for,
)
from .errors import ApiError, not_found
from .people import ConsentRow, SitePersonRow
from .vault import ERASED_NAME, ERASED_REPORT, SEALED, PersonKeyRow, PersonRef, PersonVault

RESTORE_WINDOW = timedelta(days=30)
EXPORT_PAGE_SIZE = 200
EXPORT_SPOOL_MEMORY = 8 * 1024 * 1024
PURGE_BATCH_SIZE = 25


def deletion_view(row: OrganizationRow) -> OrganizationDeletion:
    if row.deleted_at is None or row.purge_after is None:
        raise RuntimeError("workspace deletion state is incomplete")
    return OrganizationDeletion(
        organization_id=ids.encode("org", row.id),
        deleted_at=row.deleted_at,
        purge_after=row.purge_after,
    )


def _audit(
    org_id: uuid.UUID,
    actor_id: str,
    action: str,
    target_kind: str,
    target_id: str,
    details: dict[str, Any] | None = None,
) -> AuditLogRow:
    return AuditLogRow(
        id=ids.uuid7(),
        org_id=org_id,
        actor_kind="user",
        actor_id=actor_id,
        action=action,
        target_kind=target_kind,
        target_id=target_id,
        details=details or {},
    )


class WorkspaceLifecycle:
    def __init__(self, db: Database, vault: PersonVault) -> None:
        self.db = db
        self.vault = vault

    async def delete(
        self, org_id: uuid.UUID, principal_id: str, body: DeleteOrganization
    ) -> OrganizationDeletion:
        async with self.db.transaction() as session:
            row = await session.scalar(
                select(OrganizationRow).where(OrganizationRow.id == org_id).with_for_update()
            )
            if row is None:
                raise not_found("organization")
            if row.deleted_at is not None:
                raise ApiError(
                    410,
                    "WORKSPACE_DELETED",
                    "This workspace was already deleted. Restore it within 30 days or "
                    "download its export.",
                )
            if body.confirmation != row.name:
                raise ApiError(
                    422,
                    "WORKSPACE_NAME_MISMATCH",
                    "Type the workspace name exactly as it appears in Settings.",
                )
            now = await session.scalar(select(func.now()))
            if now is None:
                raise RuntimeError("database clock unavailable")
            row.deleted_at = now
            row.deleted_by = principal_id
            row.purge_after = now + RESTORE_WINDOW
            row.purged_at = None
            session.add(
                _audit(
                    org_id,
                    principal_id,
                    "organization.deleted",
                    "organization",
                    ids.encode("org", org_id),
                    {"purge_after": row.purge_after.isoformat()},
                )
            )
            await session.flush()
            return deletion_view(row)

    async def restore(self, org_id: uuid.UUID, principal_id: str) -> OrganizationRow:
        async with self.db.transaction() as session:
            row = await session.scalar(
                select(OrganizationRow).where(OrganizationRow.id == org_id).with_for_update()
            )
            if row is None:
                raise not_found("organization")
            if row.deleted_at is None:
                return row
            now = await session.scalar(select(func.now()))
            if (
                row.purged_at is not None
                or row.purge_after is None
                or now is None
                or row.purge_after <= now
            ):
                raise ApiError(
                    410,
                    "RESTORE_WINDOW_CLOSED",
                    "The 30-day restore window has ended.",
                )
            row.deleted_at = None
            row.deleted_by = None
            row.purge_after = None
            session.add(
                _audit(
                    org_id,
                    principal_id,
                    "organization.restored",
                    "organization",
                    ids.encode("org", org_id),
                )
            )
            await session.flush()
            return row

    async def export(
        self, org_id: uuid.UUID, principal_id: str
    ) -> tempfile.SpooledTemporaryFile[bytes]:
        """Build a server-side ZIP without exporting credentials, sessions or wrapped keys."""
        async with self.db.transaction() as session:
            row = await session.scalar(
                select(OrganizationRow).where(OrganizationRow.id == org_id).with_for_update()
            )
            if row is None:
                raise not_found("organization")
            now = await session.scalar(select(func.now()))
            if row.purged_at is not None or (
                row.deleted_at is not None
                and (now is None or row.purge_after is None or row.purge_after <= now)
            ):
                raise ApiError(
                    410, "RESTORE_WINDOW_CLOSED", "The workspace export window has ended."
                )
            session.add(
                _audit(
                    org_id,
                    principal_id,
                    "organization.exported",
                    "organization",
                    ids.encode("org", org_id),
                    {"deleted": row.deleted_at is not None},
                )
            )

        # Ownership passes to the streaming response, which closes it after sending the archive.
        spool = tempfile.SpooledTemporaryFile(max_size=EXPORT_SPOOL_MEMORY, mode="w+b")  # noqa: SIM115
        try:
            with acting_for(org_id, principal_id, actor=f"user:{principal_id}"):
                async with self.db.read() as session:
                    with zipfile.ZipFile(
                        spool, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
                    ) as archive:
                        await _write_query(
                            archive,
                            "workspace.json",
                            session,
                            select(
                                OrganizationRow.id,
                                OrganizationRow.name,
                                OrganizationRow.slug,
                                OrganizationRow.kind,
                                OrganizationRow.timezone,
                                OrganizationRow.data_region,
                                OrganizationRow.plan,
                                OrganizationRow.created_at,
                                OrganizationRow.deleted_at,
                                OrganizationRow.purge_after,
                            ).where(OrganizationRow.id == org_id),
                            _mapping,
                        )
                        await _write_query(
                            archive,
                            "sites.json",
                            session,
                            select(
                                SiteRow.id,
                                SiteRow.name,
                                SiteRow.kind,
                                SiteRow.mode,
                                SiteRow.timezone,
                                SiteRow.current_model_id,
                                SiteRow.created_at,
                                SiteRow.archived_at,
                            )
                            .where(SiteRow.org_id == org_id)
                            .order_by(SiteRow.created_at, SiteRow.id),
                            _mapping,
                        )
                        await _write_query(
                            archive,
                            "site_models.json",
                            session,
                            select(
                                SiteModelRow.id,
                                SiteModelRow.site_id,
                                SiteModelRow.version,
                                SiteModelRow.status,
                                SiteModelRow.spec,
                                SiteModelRow.spec_sha256,
                                SiteModelRow.validation,
                                SiteModelRow.source,
                                SiteModelRow.created_by,
                                SiteModelRow.created_at,
                                SiteModelRow.published_at,
                            )
                            .where(SiteModelRow.org_id == org_id)
                            .order_by(SiteModelRow.created_at, SiteModelRow.id),
                            _mapping,
                        )
                        await self._write_people(archive, session, org_id)
                        await _write_query(
                            archive,
                            "consents.json",
                            session,
                            select(
                                ConsentRow.id,
                                ConsentRow.site_id,
                                ConsentRow.person_id,
                                ConsentRow.purpose,
                                ConsentRow.notice_version,
                                ConsentRow.language,
                                ConsentRow.channel,
                                ConsentRow.granted_at,
                                ConsentRow.withdrawn_at,
                                ConsentRow.evidence,
                            )
                            .where(ConsentRow.org_id == org_id)
                            .order_by(ConsentRow.granted_at, ConsentRow.id),
                            _mapping,
                        )
                        await self._write_investigations(archive, session, org_id)
                        await _write_query(
                            archive,
                            "questions.json",
                            session,
                            select(
                                QuestionRow.id,
                                QuestionRow.investigation_id,
                                QuestionRow.participant_id,
                                QuestionRow.probe_id,
                                QuestionRow.location_id,
                                QuestionRow.requires_move,
                                QuestionRow.language,
                                QuestionRow.text,
                                QuestionRow.status,
                                QuestionRow.kind,
                                QuestionRow.asked_at,
                                QuestionRow.answered_at,
                            )
                            .where(QuestionRow.org_id == org_id)
                            .order_by(QuestionRow.id),
                            _mapping,
                        )
                        await self._write_observations(archive, session, org_id)
                        await _write_query(
                            archive,
                            "approvals.json",
                            session,
                            select(
                                ApprovalRow.id,
                                ApprovalRow.investigation_id,
                                ApprovalRow.action,
                                ApprovalRow.target,
                                ApprovalRow.participant_id,
                                ApprovalRow.status,
                                ApprovalRow.rationale,
                                ApprovalRow.requested_at,
                                ApprovalRow.requested_by,
                                ApprovalRow.approver_id,
                                ApprovalRow.decided_at,
                            )
                            .where(ApprovalRow.org_id == org_id)
                            .order_by(ApprovalRow.id),
                            _mapping,
                        )
                        await _write_query(
                            archive,
                            "events.json",
                            session,
                            select(
                                EventRow.seq,
                                EventRow.investigation_id,
                                EventRow.type,
                                EventRow.payload,
                                EventRow.ts,
                            )
                            .where(EventRow.org_id == org_id)
                            .order_by(EventRow.seq),
                            _mapping,
                        )
                        await _write_query(
                            archive,
                            "members.json",
                            session,
                            select(
                                MembershipRow.user_id,
                                UserRow.display_name,
                                UserRow.email,
                                MembershipRow.roles,
                                MembershipRow.status,
                                MembershipRow.created_at,
                            )
                            .join(UserRow, UserRow.id == MembershipRow.user_id)
                            .where(MembershipRow.org_id == org_id)
                            .order_by(MembershipRow.created_at, MembershipRow.user_id),
                            _mapping,
                        )
                        await _write_query(
                            archive,
                            "invitations.json",
                            session,
                            select(
                                InvitationRow.id,
                                InvitationRow.email,
                                InvitationRow.roles,
                                InvitationRow.invited_by,
                                InvitationRow.created_at,
                                InvitationRow.expires_at,
                                InvitationRow.accepted_at,
                                InvitationRow.accepted_by,
                                InvitationRow.revoked_at,
                            )
                            .where(InvitationRow.org_id == org_id)
                            .order_by(InvitationRow.created_at, InvitationRow.id),
                            _mapping,
                        )
                        await _write_query(
                            archive,
                            "audit_log.json",
                            session,
                            select(
                                AuditLogRow.id,
                                AuditLogRow.actor_kind,
                                AuditLogRow.actor_id,
                                AuditLogRow.action,
                                AuditLogRow.target_kind,
                                AuditLogRow.target_id,
                                AuditLogRow.details,
                                AuditLogRow.ts,
                            )
                            .where(AuditLogRow.org_id == org_id)
                            .order_by(AuditLogRow.ts, AuditLogRow.id),
                            _mapping,
                        )
            spool.seek(0)
            return spool
        except Exception:
            spool.close()
            raise

    async def _write_people(
        self, archive: zipfile.ZipFile, session: AsyncSession, org_id: uuid.UUID
    ) -> None:
        query = (
            select(
                SitePersonRow.org_id,
                SitePersonRow.site_id,
                SitePersonRow.id,
                SitePersonRow.spec,
                SitePersonRow.display_name_enc,
                SitePersonRow.version,
                SitePersonRow.created_at,
                SitePersonRow.updated_at,
                PersonKeyRow.wrapped_key,
            )
            .outerjoin(
                PersonKeyRow,
                (PersonKeyRow.org_id == SitePersonRow.org_id)
                & (PersonKeyRow.site_id == SitePersonRow.site_id)
                & (PersonKeyRow.person_id == SitePersonRow.id),
            )
            .where(SitePersonRow.org_id == org_id)
            .order_by(SitePersonRow.created_at, SitePersonRow.site_id, SitePersonRow.id)
        )
        result = await session.stream(query)
        with archive.open("people.json", mode="w") as output:
            output.write(b"[\n")
            first = True
            async for row in result.mappings():
                ref = PersonRef(row["org_id"], row["site_id"], row["id"])
                wrapped = row["wrapped_key"]
                encrypted_name = row["display_name_enc"]
                spec = dict(row["spec"])
                stored_name = spec.get("display_name", SEALED)
                name = stored_name if stored_name != SEALED else ERASED_NAME
                if wrapped is not None and encrypted_name is not None:
                    key = self.vault.master.unwrap(wrapped, ref)
                    name = self.vault.decrypt(key, ref, "display_name", encrypted_name)
                spec["display_name"] = name
                record = {
                    "site_id": row["site_id"],
                    "person_id": row["id"],
                    "name": name,
                    "spec": spec,
                    "version": row["version"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
                _write_json_record(output, record, first)
                first = False
            output.write(b"\n]\n")
        await result.close()

    async def _write_investigations(
        self, archive: zipfile.ZipFile, session: AsyncSession, org_id: uuid.UUID
    ) -> None:
        with archive.open("investigations.json", mode="w") as output:
            output.write(b"[\n")
            first = True
            after: tuple[datetime, str] | None = None
            while True:
                query = select(InvestigationRow).where(InvestigationRow.org_id == org_id)
                if after is not None:
                    query = query.where(
                        tuple_(InvestigationRow.created_at, InvestigationRow.id) > after
                    )
                rows = list(
                    await session.scalars(
                        query.order_by(InvestigationRow.created_at, InvestigationRow.id).limit(
                            EXPORT_PAGE_SIZE
                        )
                    )
                )
                if not rows:
                    break
                texts = await self.vault.texts(session, org_id, [row.id for row in rows])
                for row in rows:
                    request = row.request
                    report = dict(request.get("report") or {})
                    reporter_id = str(report.get("reporter_id", ""))
                    report_text = report.get("text", SEALED)
                    if report_text == SEALED:
                        report_text = texts.get((row.id, "report", reporter_id), ERASED_REPORT)
                    participants = [
                        {
                            **participant,
                            "display_name": (
                                texts.get(
                                    (row.id, "name", str(participant.get("id", ""))),
                                    ERASED_NAME,
                                )
                                if participant.get("display_name") == SEALED
                                else participant.get("display_name", ERASED_NAME)
                            ),
                        }
                        for participant in request.get("participants", [])
                    ]
                    record = {
                        "id": row.id,
                        "pack_id": row.pack_id,
                        "site_id": row.site_id,
                        "site_model_id": row.site_model_id,
                        "status": row.status,
                        "created_at": row.created_at,
                        "updated_at": row.updated_at,
                        "participants": participants,
                        "report": {**report, "text": report_text},
                        "outcome": row.outcome,
                        "ground_truth": row.ground_truth,
                        "version": row.version,
                    }
                    _write_json_record(output, record, first)
                    first = False
                last = rows[-1]
                after = (last.created_at, last.id)
            output.write(b"\n]\n")

    async def _write_observations(
        self, archive: zipfile.ZipFile, session: AsyncSession, org_id: uuid.UUID
    ) -> None:
        with archive.open("observations.json", mode="w") as output:
            output.write(b"[\n")
            first = True
            after: str | None = None
            while True:
                query = select(ObservationRow).where(ObservationRow.org_id == org_id)
                if after is not None:
                    query = query.where(ObservationRow.id > after)
                rows = list(
                    await session.scalars(query.order_by(ObservationRow.id).limit(EXPORT_PAGE_SIZE))
                )
                if not rows:
                    break
                texts = await self.vault.texts(
                    session, org_id, list({row.investigation_id for row in rows})
                )
                for row in rows:
                    record = {
                        "id": row.id,
                        "investigation_id": row.investigation_id,
                        "question_id": row.question_id,
                        "participant_id": row.participant_id,
                        "probe_id": row.probe_id,
                        "location_id": row.location_id,
                        "outcome": row.outcome,
                        "hedge": row.hedge,
                        "directness": row.directness,
                        "modality": row.modality,
                        "transcript": (
                            row.transcript
                            if row.transcript is not None
                            else texts.get((row.investigation_id, "transcript", row.id))
                        ),
                        "extraction_method": row.extraction_method,
                        "injection_suspected": row.injection_suspected,
                        "state": row.state,
                        "committed_at": row.committed_at,
                    }
                    _write_json_record(output, record, first)
                    first = False
                after = rows[-1].id
            output.write(b"\n]\n")


async def _write_query(
    archive: zipfile.ZipFile,
    filename: str,
    session: AsyncSession,
    query: Any,
    transform: Callable[[RowMapping], dict[str, Any]],
) -> None:
    result = await session.stream(query)
    with archive.open(filename, mode="w") as output:
        output.write(b"[\n")
        first = True
        async for row in result.mappings():
            _write_json_record(output, transform(row), first)
            first = False
        output.write(b"\n]\n")
    await result.close()


def _mapping(row: RowMapping) -> dict[str, Any]:
    return dict(row)


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, uuid.UUID)):
        return value.isoformat() if isinstance(value, datetime) else str(value)
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(f"cannot export {type(value).__name__}")


def _write_json_record(output: Any, record: dict[str, Any], first: bool) -> None:
    if not first:
        output.write(b",\n")
    output.write(
        json.dumps(
            record,
            default=_json_default,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )


async def purge_deleted_organizations(db: Database, *, now: datetime | None = None) -> int:
    """Purge due workspaces while retaining event logs, projections and pinned models for replay.

    Run as the migration/table-owner role. Person keys are shredded before ciphertext and
    directory rows are removed. Events and audit entries are append-only and remain intact.
    """
    purged = 0
    while True:
        async with db.transaction() as session:
            clock = now or await session.scalar(select(func.now()))
            if clock is None:
                raise RuntimeError("database clock unavailable")
            due = list(
                await session.scalars(
                    select(OrganizationRow)
                    .where(
                        OrganizationRow.deleted_at.is_not(None),
                        OrganizationRow.purge_after <= clock,
                        OrganizationRow.purged_at.is_(None),
                    )
                    .order_by(OrganizationRow.purge_after, OrganizationRow.id)
                    .limit(PURGE_BATCH_SIZE)
                    .with_for_update(skip_locked=True)
                )
            )
            for organization in due:
                await _purge_one(session, organization, clock)
            purged += len(due)
        if len(due) < PURGE_BATCH_SIZE:
            break
    return purged


async def _purge_one(session: AsyncSession, organization: OrganizationRow, now: datetime) -> None:
    org_id = organization.id
    target = ids.encode("org", org_id)
    await session.execute(
        text(
            "select set_config('app.org_id', :org, true), "
            "set_config('app.purge_personal_data', 'on', true)"
        ),
        {"org": str(org_id)},
    )

    # A formerly unsealed or hand-written investigation row must not keep report/name text in
    # its mutable projection. Replay reads none of these fields, and event rows remain untouched.
    investigations = list(
        await session.scalars(
            select(InvestigationRow).where(InvestigationRow.org_id == org_id).with_for_update()
        )
    )
    for investigation in investigations:
        request = dict(investigation.request)
        report = dict(request.get("report") or {})
        if "text" in report:
            report["text"] = SEALED
        request["report"] = report
        request["participants"] = [
            {**participant, "display_name": SEALED}
            for participant in request.get("participants", [])
        ]
        investigation.request = request

    # The current event schema stores person ids, outcomes and redacted text. Abort if an older
    # log violates that invariant: rewriting it would break the seal and exact replay.
    unsafe_events = await session.scalar(
        select(func.count())
        .select_from(EventRow)
        .where(
            EventRow.org_id == org_id,
            ((EventRow.type == "ReportReceived") & (EventRow.payload["text"].astext != SEALED))
            | (
                (EventRow.type == "InvestigationCreated")
                & text(
                    "exists (select 1 from jsonb_array_elements(events.payload->'participants') p "
                    "where coalesce(p->>'display_name', '') not in ('-', ''))"
                )
            ),
        )
    )
    if unsafe_events:
        raise ApiError(
            409,
            "PURGE_REQUIRES_EVENT_REDACTION",
            "This workspace has personal text in its append-only event log and needs "
            "a reviewed migration before purge.",
        )

    await session.execute(
        update(PersonKeyRow)
        .where(PersonKeyRow.org_id == org_id)
        .values(wrapped_key=None, erased_at=func.coalesce(PersonKeyRow.erased_at, now))
    )
    # Ciphertext references person_keys, so remove it before deleting the key rows.
    await session.execute(text("delete from personal_texts where org_id = :org"), {"org": org_id})
    await session.execute(delete(ConsentRow).where(ConsentRow.org_id == org_id))
    await session.execute(delete(SitePersonRow).where(SitePersonRow.org_id == org_id))
    await session.execute(delete(PersonKeyRow).where(PersonKeyRow.org_id == org_id))
    await session.execute(delete(InvitationRow).where(InvitationRow.org_id == org_id))
    await session.execute(delete(MembershipRow).where(MembershipRow.org_id == org_id))
    await session.execute(delete(IdempotencyRow).where(IdempotencyRow.org_id == org_id))
    await session.execute(delete(ObservationRow).where(ObservationRow.org_id == org_id))
    await session.execute(delete(QuestionRow).where(QuestionRow.org_id == org_id))
    await session.execute(delete(ApprovalRow).where(ApprovalRow.org_id == org_id))
    await session.execute(
        delete(SiteModelRow).where(SiteModelRow.org_id == org_id, SiteModelRow.status == "draft")
    )
    await session.execute(
        update(SiteModelRow)
        .where(SiteModelRow.org_id == org_id)
        .values(source=null(), validation=null(), created_by=None)
    )
    await session.execute(
        update(SiteRow).where(SiteRow.org_id == org_id).values(name="Deleted site")
    )
    await session.execute(
        update(OnboardingRow)
        .where(OnboardingRow.org_id == org_id)
        .values(
            org_id=None,
            step="welcome",
            answers={"version": 1},
            dismissed_at=None,
            completed_at=None,
        )
    )
    org_ref = ids.encode("org", org_id)
    await session.execute(
        update(PreferenceRow).where(PreferenceRow.last_org_id == org_id).values(last_org_id=None)
    )
    await session.execute(
        update(PreferenceRow)
        .where(PreferenceRow.last_site_by_org.has_key(org_ref))
        .values(last_site_by_org=PreferenceRow.last_site_by_org.op("-")(org_ref))
    )

    organization.name = "Deleted workspace"
    organization.slug = f"purged-{org_id.hex}"
    organization.created_by = None
    organization.deleted_by = None
    organization.purged_at = now
    session.add(
        AuditLogRow(
            id=ids.uuid7(),
            org_id=org_id,
            actor_kind="system",
            actor_id="system:workspace-purge",
            action="organization.purged",
            target_kind="organization",
            target_id=target,
            details={"retained": ["append_only_events", "audit_log", "investigation_replay_data"]},
        )
    )
    await session.flush()
