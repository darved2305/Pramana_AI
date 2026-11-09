"""Durable email delivery through a PostgreSQL outbox.

SMTP is at-least-once: a process can stop after the server accepts a message but before the
database records success. Each attempt is committed before sending and carries the stable outbox
id, so that narrow uncertainty is visible and can be correlated instead of being silent.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import ids
from .account_rows import InvitationRow
from .db import Base, Database, acting_as_job, acting_for, apply_context
from .mail import Mailer

RELAY_JOB = "email-outbox-relay"
RELAY_LOCK_KEY = 0x5052414D414E41
MAX_ATTEMPTS = 5
LOCK_LEASE = timedelta(minutes=2)
MAX_BACKOFF_S = 6 * 60 * 60
MAX_MESSAGES_PER_DRAIN = 10


class EmailOutboxRow(Base):
    __tablename__ = "email_outbox"
    __table_args__ = (
        UniqueConstraint("org_id", "id", name="email_outbox_org_id"),
        UniqueConstraint("invitation_id", name="email_outbox_invitation"),
        CheckConstraint(
            "(kind = 'invitation' and invitation_id is not null and consent_link_id is null) or "
            "(kind = 'consent_request' and consent_link_id is not null "
            "and invitation_id is null) or "
            "(kind not in ('invitation', 'consent_request') and invitation_id is null "
            "and consent_link_id is null)",
            name="email_outbox_source",
        ),
        UniqueConstraint("consent_link_id", name="email_outbox_consent_link"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    kind: Mapped[str] = mapped_column(String(48), default="invitation", server_default="invitation")
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invitations.id", ondelete="CASCADE"), nullable=True
    )
    consent_link_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("consent_links.id", ondelete="CASCADE"), nullable=True
    )
    state: Mapped[str] = mapped_column(String(16))
    recipient: Mapped[str | None] = mapped_column(String(254), nullable=True)
    subject: Mapped[str | None] = mapped_column(String(998), nullable=True)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dead_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmailAttemptRow(Base):
    __tablename__ = "email_outbox_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "outbox_id"],
            ["email_outbox.org_id", "email_outbox.id"],
            name="email_outbox_attempt_org_fk",
            ondelete="CASCADE",
        ),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    outbox_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    attempt: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str] = mapped_column(String(16))
    error_type: Mapped[str | None] = mapped_column(String(80), nullable=True)


@dataclass(frozen=True)
class EmailEnvelope:
    recipient: str
    subject: str
    body: str


@dataclass(frozen=True)
class _Attempt:
    org_id: uuid.UUID
    outbox_id: uuid.UUID
    number: int
    recipient: str
    subject: str
    body: str


def invitation_email(
    *, email: str, workspace: str, inviter: str, link_base: str, accept_path: str
) -> EmailEnvelope:
    subject = " ".join(f"Join {workspace} on Pramana".split())
    body = (
        f"{inviter} invited you to join {workspace} on Pramana.\n\n"
        f"Open this link to accept:\n{link_base}{accept_path}\n\n"
        f"It works for 7 days and only when you sign in as {email}.\n"
        "If you were not expecting this, you can ignore this email.\n"
    )
    return EmailEnvelope(email, subject, body)


def queue_email(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    kind: str,
    envelope: EmailEnvelope,
    now: datetime,
) -> None:
    """Queue a message that belongs to no invitation or consent link. It joins the caller's
    transaction, so the state change and the send intent commit or roll back together."""
    session.add(
        EmailOutboxRow(
            id=ids.uuid7(),
            org_id=org_id,
            kind=kind,
            state="queued",
            recipient=envelope.recipient,
            subject=envelope.subject,
            body=envelope.body,
            attempts=0,
            available_at=now,
        )
    )


def delivery_status(state: str | None) -> str:
    if state is None:
        # Invitations created before the outbox have no durable delivery record. The old
        # request-time SMTP path did not persist whether the provider accepted the message.
        return "unknown"
    if state == "sent":
        return "sent"
    if state in {"queued", "sending"}:
        return "queued"
    return "failed"


def _backoff(attempt: int) -> timedelta:
    ceiling = min(30 * (2 ** max(attempt - 1, 0)), MAX_BACKOFF_S)
    return timedelta(seconds=random.uniform(ceiling * 0.8, ceiling * 1.2))


class EmailRelay:
    """A short-lived drain operation suitable for request background tasks and Cloud Run Jobs."""

    def __init__(self, db: Database, mailer: Mailer | None) -> None:
        self.db = db
        self.mailer = mailer

    @staticmethod
    def _dead_letter(row: EmailOutboxRow, now: datetime, reason: str) -> None:
        row.state = "dead"
        row.dead_at = now
        row.locked_until = None
        row.recipient = None
        row.subject = None
        row.body = None
        row.last_error = reason[:80]

    async def drain(self) -> dict[str, int | bool]:
        """Send due messages while holding one PostgreSQL session advisory lock."""
        async with self.db.engine.connect() as lock_connection:
            result = await lock_connection.execute(
                text("select pg_try_advisory_lock(:key)"), {"key": RELAY_LOCK_KEY}
            )
            acquired = bool(result.scalar_one())
            await lock_connection.commit()
            if not acquired:
                return {"locked": False, "sent": 0, "retried": 0, "dead": 0}
            counts = {"locked": True, "sent": 0, "retried": 0, "dead": 0}
            try:
                for _ in range(MAX_MESSAGES_PER_DRAIN):
                    action, attempt = await self._claim(lock_connection)
                    if action == "idle":
                        break
                    if action == "dead":
                        counts["dead"] += 1
                        continue
                    assert attempt is not None
                    try:
                        if self.mailer is None:
                            raise RuntimeError("email_not_configured")
                        await asyncio.to_thread(
                            self.mailer.send,
                            attempt.recipient,
                            attempt.subject,
                            attempt.body,
                            outbox_id=attempt.outbox_id,
                        )
                    except Exception as exc:
                        is_dead = await self._finish_failure(
                            lock_connection, attempt, type(exc).__name__
                        )
                        counts["dead" if is_dead else "retried"] += 1
                    else:
                        await self._finish_success(lock_connection, attempt)
                        counts["sent"] += 1
            finally:
                await lock_connection.execute(
                    text("select pg_advisory_unlock(:key)"), {"key": RELAY_LOCK_KEY}
                )
                await lock_connection.commit()
        return counts

    @asynccontextmanager
    async def _transaction(self, connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
        """Use the advisory-lock connection so a one-connection pool cannot deadlock itself."""
        async with (
            AsyncSession(bind=connection, expire_on_commit=False) as session,
            session.begin(),
        ):
            await apply_context(session)
            yield session

    async def _claim(self, connection: AsyncConnection) -> tuple[str, _Attempt | None]:
        now = datetime.now(UTC)
        with acting_as_job(RELAY_JOB):
            async with self._transaction(connection) as session:
                row = await session.scalar(
                    select(EmailOutboxRow)
                    .where(
                        or_(
                            and_(
                                EmailOutboxRow.state == "queued",
                                EmailOutboxRow.available_at <= now,
                            ),
                            and_(
                                EmailOutboxRow.state == "sending",
                                EmailOutboxRow.locked_until <= now,
                            ),
                        )
                    )
                    .order_by(EmailOutboxRow.available_at, EmailOutboxRow.created_at)
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if row is None:
                    return "idle", None

                if row.state == "sending":
                    previous = await session.get(
                        EmailAttemptRow, (row.org_id, row.id, row.attempts), with_for_update=True
                    )
                    if previous is not None and previous.finished_at is None:
                        previous.finished_at = now
                        previous.result = "uncertain"
                        previous.error_type = "RelayLeaseExpired"
                    row.last_error = "RelayLeaseExpired"

                if row.invitation_id is not None:
                    # Invitation rows are tenant-scoped. Set the matching organization while
                    # retaining the relay job identity for the outbox tables.
                    with acting_for(row.org_id, "email-outbox-relay"):
                        await apply_context(session)
                        invitation = await session.scalar(
                            select(InvitationRow).where(
                                InvitationRow.org_id == row.org_id,
                                InvitationRow.id == row.invitation_id,
                            )
                        )
                    if (
                        invitation is None
                        or invitation.accepted_at is not None
                        or invitation.revoked_at is not None
                        or invitation.expires_at <= now
                    ):
                        self._dead_letter(row, now, "InvitationNoLongerValid")
                        return "dead", None

                if row.consent_link_id is not None:
                    # The public token is single-use and may have been revoked or consumed after
                    # it was queued. Read its tenant-scoped state before sending the bearer link.
                    with acting_for(row.org_id, actor="email-outbox-relay"):
                        await apply_context(session)
                        consent_link = await session.scalar(
                            text(
                                "select id from consent_links "
                                "where org_id = :org_id and id = :id "
                                "and consumed_at is null and revoked_at is null "
                                "and expires_at > :now"
                            ),
                            {"org_id": row.org_id, "id": row.consent_link_id, "now": now},
                        )
                    if consent_link is None:
                        self._dead_letter(row, now, "ConsentLinkNoLongerValid")
                        return "dead", None

                if row.attempts >= MAX_ATTEMPTS or self.mailer is None:
                    self._dead_letter(
                        row,
                        now,
                        "EmailNotConfigured" if self.mailer is None else "AttemptsExhausted",
                    )
                    return "dead", None

                if row.recipient is None or row.subject is None or row.body is None:
                    self._dead_letter(row, now, "OutboxBodyMissing")
                    return "dead", None

                row.attempts += 1
                row.state = "sending"
                row.locked_until = now + LOCK_LEASE
                session.add(
                    EmailAttemptRow(
                        org_id=row.org_id,
                        outbox_id=row.id,
                        attempt=row.attempts,
                        result="sending",
                    )
                )
                return (
                    "send",
                    _Attempt(
                        org_id=row.org_id,
                        outbox_id=row.id,
                        number=row.attempts,
                        recipient=row.recipient,
                        subject=row.subject,
                        body=row.body,
                    ),
                )

    async def _finish_success(self, connection: AsyncConnection, attempt: _Attempt) -> None:
        now = datetime.now(UTC)
        with acting_as_job(RELAY_JOB):
            async with self._transaction(connection) as session:
                row = await session.scalar(
                    select(EmailOutboxRow)
                    .where(
                        EmailOutboxRow.org_id == attempt.org_id,
                        EmailOutboxRow.id == attempt.outbox_id,
                    )
                    .with_for_update()
                )
                history = await session.get(
                    EmailAttemptRow,
                    (attempt.org_id, attempt.outbox_id, attempt.number),
                    with_for_update=True,
                )
                if row is None or history is None or row.attempts != attempt.number:
                    return
                row.state = "sent"
                row.sent_at = now
                row.locked_until = None
                row.last_error = None
                row.recipient = None
                row.subject = None
                row.body = None
                history.finished_at = now
                history.result = "sent"

    async def _finish_failure(
        self, connection: AsyncConnection, attempt: _Attempt, error_type: str
    ) -> bool:
        now = datetime.now(UTC)
        dead = attempt.number >= MAX_ATTEMPTS
        with acting_as_job(RELAY_JOB):
            async with self._transaction(connection) as session:
                row = await session.scalar(
                    select(EmailOutboxRow)
                    .where(
                        EmailOutboxRow.org_id == attempt.org_id,
                        EmailOutboxRow.id == attempt.outbox_id,
                    )
                    .with_for_update()
                )
                history = await session.get(
                    EmailAttemptRow,
                    (attempt.org_id, attempt.outbox_id, attempt.number),
                    with_for_update=True,
                )
                if row is None or history is None or row.attempts != attempt.number:
                    return dead
                row.state = "dead" if dead else "queued"
                row.dead_at = now if dead else None
                row.available_at = now + _backoff(attempt.number)
                row.locked_until = None
                row.last_error = error_type[:80]
                if dead:
                    row.recipient = None
                    row.subject = None
                    row.body = None
                history.finished_at = now
                history.result = "dead" if dead else "retry"
                history.error_type = error_type[:80]
        return dead
