"""Workspace invitations: create, list, revoke, accept.

The link is ``/invite/<org id>.<secret>``. Only the SHA-256 of the secret is stored, so the
database alone cannot be used to join. The organization id in the link lets acceptance run
inside that organization's row-level security context; the secret is what proves the invite.
The invited address must be the signed-in person's verified email.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import ColumnElement, func, select

from pramana_contracts import CreateInvitation, InvitationAccepted, InvitationView

from . import ids
from .account_rows import InvitationRow
from .accounts import organization_view
from .auth.service import Principal
from .db import AuditLogRow, Database, MembershipRow, OrganizationRow, UserRow, acting_for
from .errors import ApiError, not_found
from .mail import Mailer
from .observability import log

LIFETIME = timedelta(days=7)
SEND_TIMEOUT_S = 6.0
INVALID = "this invitation link is not valid"


def _hash(secret: str) -> bytes:
    return hashlib.sha256(secret.encode()).digest()


def _status(row: InvitationRow, now: datetime) -> str:
    if row.accepted_at is not None:
        return "accepted"
    if row.revoked_at is not None:
        return "revoked"
    return "expired" if row.expires_at <= now else "pending"


def invitation_view(row: InvitationRow, inviter: str | None) -> InvitationView:
    return InvitationView.model_validate(
        {
            "id": ids.encode("invite", row.id),
            "email": row.email,
            "roles": sorted(row.roles),
            "status": _status(row, datetime.now(UTC)),
            "created_at": row.created_at,
            "expires_at": row.expires_at,
            "invited_by": inviter,
        }
    )


def _audit(org_id: uuid.UUID, actor: str, action: str, row: InvitationRow) -> AuditLogRow:
    return AuditLogRow(
        id=ids.uuid7(),
        org_id=org_id,
        actor_kind="user",
        actor_id=actor,
        action=action,
        target_kind="invitation",
        target_id=ids.encode("invite", row.id),
        details={"roles": sorted(row.roles)},
    )


Delivery = Literal["sent", "failed", "not_configured"]


async def email_invitation(
    mailer: Mailer | None,
    link_base: str | None,
    row: InvitationRow,
    workspace: str,
    inviter: str,
    accept_path: str,
) -> Delivery:
    """Email the accept link. Never raises: the invitation stands whatever happens here.

    The link holds the secret, so failures are logged by type only, without the message.
    On a timeout the worker thread may still finish, so "failed" means "not confirmed".
    """
    if mailer is None or not link_base:
        return "not_configured"
    subject = " ".join(f"Join {workspace} on Pramana".split())
    text = (
        f"{inviter} invited you to join {workspace} on Pramana.\n\n"
        f"Open this link to accept:\n{link_base}{accept_path}\n\n"
        f"It works for 7 days and only when you sign in as {row.email}.\n"
        "If you were not expecting this, you can ignore this email.\n"
    )
    try:
        await asyncio.wait_for(
            asyncio.to_thread(mailer.send, row.email, subject, text), SEND_TIMEOUT_S
        )
    except Exception as exc:
        log.warning(
            "invitation_email_not_confirmed",
            error=type(exc).__name__,
            invitation=ids.encode("invite", row.id),
        )
        return "failed"
    return "sent"


def _mask(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:2]}{'*' * max(len(local) - 2, 1)}@{domain}"


class Invitations:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def create(
        self, org_id: uuid.UUID, principal: Principal, body: CreateInvitation
    ) -> tuple[InvitationRow, str]:
        secret = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        async with self.db.transaction() as session:
            member = await session.scalar(
                select(MembershipRow.user_id)
                .join(UserRow, UserRow.id == MembershipRow.user_id)
                .where(MembershipRow.org_id == org_id, func.lower(UserRow.email) == body.email)
            )
            if member is not None:
                raise ApiError(409, "ALREADY_MEMBER", "this person is already in the workspace")
            open_row = await session.scalar(
                select(InvitationRow)
                .where(
                    InvitationRow.org_id == org_id,
                    InvitationRow.email == body.email,
                    InvitationRow.accepted_at.is_(None),
                    InvitationRow.revoked_at.is_(None),
                )
                .with_for_update()
            )
            if open_row is not None:
                # A new link replaces the old one, so a lost link is never a dead end.
                open_row.revoked_at = now
                await session.flush()
            row = InvitationRow(
                id=ids.uuid7(),
                org_id=org_id,
                email=body.email,
                roles=list(body.roles),
                token_hash=_hash(secret),
                invited_by=principal.id,
                created_at=now,
                expires_at=now + LIFETIME,
            )
            session.add(row)
            session.add(_audit(org_id, principal.id, "invitation.created", row))
            await session.flush()
        return row, f"{ids.encode('org', org_id)}.{secret}"

    async def listing(self, org_id: uuid.UUID) -> list[tuple[InvitationRow, str | None]]:
        async with self.db.read() as session:
            rows = (
                await session.execute(
                    select(InvitationRow, UserRow.display_name)
                    .outerjoin(UserRow, UserRow.id == InvitationRow.invited_by)
                    .where(InvitationRow.org_id == org_id)
                    .order_by(InvitationRow.created_at.desc())
                    .limit(200)
                )
            ).all()
        return [(r, name) for r, name in rows]

    async def revoke(self, org_id: uuid.UUID, principal: Principal, invite_id: uuid.UUID) -> None:
        async with self.db.transaction() as session:
            row = await session.scalar(
                select(InvitationRow)
                .where(InvitationRow.org_id == org_id, InvitationRow.id == invite_id)
                .with_for_update()
            )
            if row is None:
                raise not_found("invitation")
            if row.accepted_at is not None:
                raise ApiError(409, "INVITATION_USED", "this invitation was already accepted")
            if row.revoked_at is None:
                row.revoked_at = datetime.now(UTC)
                session.add(_audit(org_id, principal.id, "invitation.revoked", row))

    async def accept(self, principal: Principal, token: str) -> InvitationAccepted:
        org_ref, _, secret = token.partition(".")
        try:
            org_id = ids.decode("org", org_ref)
        except ValueError as exc:
            raise ApiError(404, "INVITATION_NOT_FOUND", INVALID) from exc
        if not secret:
            raise ApiError(404, "INVITATION_NOT_FOUND", INVALID)
        return await self._join(
            principal, org_id, InvitationRow.token_hash == _hash(secret), hide_email=False
        )

    async def accept_pending(
        self, principal: Principal, org_ref: str, invite_ref: str
    ) -> InvitationAccepted:
        """Join from the list in ``/v1/me``. The verified email is the proof here."""
        try:
            org_id, invite_id = ids.decode("org", org_ref), ids.decode("invite", invite_ref)
        except ValueError as exc:
            raise ApiError(404, "INVITATION_NOT_FOUND", INVALID) from exc
        return await self._join(principal, org_id, InvitationRow.id == invite_id, hide_email=True)

    async def _join(
        self,
        principal: Principal,
        org_id: uuid.UUID,
        match: ColumnElement[bool],
        *,
        hide_email: bool,
    ) -> InvitationAccepted:
        if not principal.email_verified:
            raise ApiError(
                403, "EMAIL_VERIFICATION_REQUIRED", "verify your email before joining a workspace"
            )
        now = datetime.now(UTC)
        with acting_for(org_id, principal.id, actor=f"user:{principal.id}"):
            async with self.db.transaction() as session:
                # A hash lookup: equality on a 256-bit digest leaks nothing useful.
                row = await session.scalar(
                    select(InvitationRow)
                    .where(InvitationRow.org_id == org_id, match)
                    .with_for_update()
                )
                if row is None:
                    raise ApiError(404, "INVITATION_NOT_FOUND", INVALID)
                if row.accepted_at is not None and row.accepted_by != principal.id:
                    raise ApiError(409, "INVITATION_USED", "this invitation was already used")
                if row.revoked_at is not None:
                    raise ApiError(410, "INVITATION_REVOKED", "this invitation was withdrawn")
                if row.accepted_at is None and row.expires_at <= now:
                    raise ApiError(410, "INVITATION_EXPIRED", "this invitation has expired")
                if principal.email.lower() != row.email:
                    if hide_email:
                        raise ApiError(404, "INVITATION_NOT_FOUND", INVALID)
                    raise ApiError(
                        403,
                        "INVITATION_EMAIL_MISMATCH",
                        f"this invitation is for {_mask(row.email)}; sign in with that account",
                    )
                org = await session.scalar(
                    select(OrganizationRow).where(
                        OrganizationRow.id == org_id, OrganizationRow.deleted_at.is_(None)
                    )
                )
                if org is None:
                    raise ApiError(404, "INVITATION_NOT_FOUND", "this workspace no longer exists")
                member = await session.scalar(
                    select(MembershipRow)
                    .where(MembershipRow.org_id == org_id, MembershipRow.user_id == principal.id)
                    .with_for_update()
                )
                if member is None:
                    member = MembershipRow(
                        org_id=org_id, user_id=principal.id, roles=sorted(row.roles)
                    )
                    session.add(member)
                elif row.accepted_at is None:
                    member.roles = sorted(set(member.roles) | set(row.roles))
                    member.status = "active"
                if row.accepted_at is None:
                    row.accepted_at, row.accepted_by = now, principal.id
                    session.add(_audit(org_id, principal.id, "invitation.accepted", row))
                await session.flush()
                summary = organization_view(org, list(member.roles))
        return InvitationAccepted(organization=summary, destination=f"/app/{summary.slug}")
