"""Persistence: an append-only event log plus read projections, on PostgreSQL.

Events are the source of truth for rebuilding an investigation's engine. Projections
(``investigations``, ``questions``, ``observations``) exist for queries and are written in the
same transaction as the events that produce them. One ``AsyncSession`` is created per unit of
work and never shared between concurrent tasks.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, ClassVar, cast

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.schema import FetchedValue

from .settings import Settings

current_org: ContextVar[uuid.UUID | None] = ContextVar("current_org", default=None)
"""The organization this unit of work acts for. Every transaction copies it into the
transaction-local setting ``app.org_id``, which row-level security reads (ADR 0015). Unset means
no tenant rows are visible to the runtime role."""

current_user: ContextVar[str | None] = ContextVar("current_user", default=None)
"""The signed-in user, copied into ``app.user_id``: lets a person read their own memberships
across organizations, nothing else."""

current_actor: ContextVar[str | None] = ContextVar("current_actor", default=None)
current_job: ContextVar[str | None] = ContextVar("current_job", default=None)

current_hosted_domain: ContextVar[str | None] = ContextVar("current_hosted_domain", default=None)


@contextmanager
def acting_for(
    org_id: uuid.UUID | None,
    user_id: str | None = None,
    *,
    actor: str | None = None,
    hosted_domain: str | None = None,
) -> Iterator[None]:
    """Run the enclosed work in an organization context (and optionally as a user)."""
    org_token = current_org.set(org_id)
    user_token = current_user.set(user_id) if user_id is not None else None
    actor_token = current_actor.set(actor) if actor is not None else None
    domain_token = current_hosted_domain.set(hosted_domain)
    try:
        yield
    finally:
        current_org.reset(org_token)
        if user_token is not None:
            current_user.reset(user_token)
        if actor_token is not None:
            current_actor.reset(actor_token)
        current_hosted_domain.reset(domain_token)


async def apply_context(session: AsyncSession) -> None:
    """Copy the context into the current transaction (``set_config(..., true)``: transaction-local,
    so a pooled connection never carries one request's organization into the next)."""
    org, user, job, hosted_domain = (
        current_org.get(),
        current_user.get(),
        current_job.get(),
        current_hosted_domain.get(),
    )
    actor = current_actor.get() or (f"user:{user}" if user else "")
    await session.execute(
        text(
            "select set_config('app.org_id', :org, true), "
            "set_config('app.user_id', :user, true), set_config('app.principal', :actor, true), "
            "set_config('app.job', :job, true), "
            "set_config('app.hosted_domain', :hosted_domain, true)"
        ),
        {
            "org": str(org) if org else "",
            "user": user or "",
            "actor": actor,
            "job": job or "",
            "hosted_domain": hosted_domain or "",
        },
    )


@contextmanager
def acting_as_job(name: str) -> Iterator[None]:
    """Set the transaction-local job identity used by narrowly scoped worker RLS policies."""
    token = current_job.set(name)
    try:
        yield
    finally:
        current_job.reset(token)


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSONB}


def org_column() -> Mapped[uuid.UUID]:
    """``org_id`` on a tenant table. The database fills it from the organization context (and,
    during the expand step, falls back to the demo organization for the table owner only)."""
    return mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), server_default=FetchedValue()
    )


class InvestigationRow(Base):
    __tablename__ = "investigations"

    org_id: Mapped[uuid.UUID] = org_column()

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    pack_id: Mapped[str] = mapped_column(String(64))
    site_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    site_model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    scenario_id: Mapped[str] = mapped_column(String(64))
    commitment: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict[str, Any]] = mapped_column(JSONB)
    """The validated ``CreateInvestigation`` payload (participants, report, scenario seed)."""
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ground_truth: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    """Incremented on every committed change; detects stale in-memory engines."""
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("investigations_created_at", "created_at"),
        UniqueConstraint("org_id", "id", name="investigations_org_id"),
        ForeignKeyConstraint(
            ["org_id", "site_id", "site_model_id"],
            ["site_models.org_id", "site_models.site_id", "site_models.id"],
            name="investigations_model_pin_fk",
        ),
    )


class EventRow(Base):
    __tablename__ = "events"

    org_id: Mapped[uuid.UUID] = org_column()

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("events_inv_seq", "investigation_id", "seq"),
        ForeignKeyConstraint(
            ["org_id", "investigation_id"],
            ["investigations.org_id", "investigations.id"],
            name="events_org_investigation_fk",
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "investigation_id", "idempotency_key", name="events_investigation_idempotency"
        ),
    )


class QuestionRow(Base):
    __tablename__ = "questions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "investigation_id"],
            ["investigations.org_id", "investigations.id"],
            name="questions_org_investigation_fk",
            ondelete="CASCADE",
        ),
    )

    org_id: Mapped[uuid.UUID] = org_column()

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    participant_id: Mapped[str] = mapped_column(String(64))
    probe_id: Mapped[str] = mapped_column(String(64))
    location_id: Mapped[str] = mapped_column(String(64))
    requires_move: Mapped[bool] = mapped_column(Boolean)
    language: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16), default="probe", server_default="probe")
    asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ObservationRow(Base):
    __tablename__ = "observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "investigation_id"],
            ["investigations.org_id", "investigations.id"],
            name="observations_org_investigation_fk",
            ondelete="CASCADE",
        ),
    )

    org_id: Mapped[uuid.UUID] = org_column()

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    participant_id: Mapped[str] = mapped_column(String(64))
    probe_id: Mapped[str] = mapped_column(String(64))
    location_id: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str] = mapped_column(String(32))
    hedge: Mapped[str] = mapped_column(String(16))
    directness: Mapped[str] = mapped_column(String(16))
    modality: Mapped[str] = mapped_column(String(16))
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_method: Mapped[str] = mapped_column(String(16))
    injection_suspected: Mapped[bool] = mapped_column(Boolean, default=False)
    state: Mapped[str] = mapped_column(String(16))
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApprovalRow(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "investigation_id"],
            ["investigations.org_id", "investigations.id"],
            name="approvals_org_investigation_fk",
            ondelete="CASCADE",
        ),
    )

    org_id: Mapped[uuid.UUID] = org_column()

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(64))
    participant_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    rationale: Mapped[str] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    requested_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """The signed-in account that asked; ``None`` for automation and open mode."""
    approver_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    capability_jti: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    """The approval's current capability. At most one is live: a new one replaces it only
    after it has expired."""


class VoiceUsageRow(Base):
    """One metered Gnani call: billable units (audio seconds or characters) and priced cost."""

    __tablename__ = "voice_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    service: Mapped[str] = mapped_column(String(16))
    units: Mapped[float] = mapped_column(Float)
    cost_inr: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserRow(Base):
    """A staff member who signs in to the console (operator and/or approver)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    """Stored lower-cased; compared case-insensitively."""
    display_name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    roles: Mapped[list[str]] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SessionRow(Base):
    """A browser session. Only the SHA-256 of the cookie value is stored."""

    __tablename__ = "sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    auth_method: Mapped[str] = mapped_column(String(16), server_default="password")
    hosted_domain: Mapped[str | None] = mapped_column(String(253), nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    idle_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now() + interval '60 minutes'")
    )
    absolute_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now() + interval '12 hours'")
    )
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)


class UserIdentityRow(Base):
    __tablename__ = "user_identities"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(16))
    subject: Mapped[str] = mapped_column(String(255))
    email_at_link: Mapped[str | None] = mapped_column(String(254), nullable=True)
    hosted_domain: Mapped[str | None] = mapped_column(String(253), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthFlowRow(Base):
    __tablename__ = "auth_flows"

    id_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(128))
    nonce: Mapped[str] = mapped_column(String(128))
    pkce_verifier: Mapped[str] = mapped_column(String(128))
    next_path: Mapped[str] = mapped_column(String(2048))
    link_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    link_session_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RateLimitRow(Base):
    __tablename__ = "rate_limits"

    scope: Mapped[str] = mapped_column(String(32), primary_key=True)
    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[list[float]] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditLogRow(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    actor_kind: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(80))
    target_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DirectoryParticipantRow(Base):
    """A person in a site's directory. ``spec`` is a validated ``ParticipantSpec``."""

    __tablename__ = "directory_participants"

    org_id: Mapped[uuid.UUID] = org_column()

    pack_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OrganizationRow(Base):
    """A customer: a campus, hospital, office or hotel group (ADR 0015)."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16))
    version: Mapped[int] = mapped_column(Integer, server_default="1")
    timezone: Mapped[str] = mapped_column(String(64), server_default="Asia/Kolkata")
    data_region: Mapped[str] = mapped_column(String(32), server_default="asia-south1")
    plan: Mapped[str] = mapped_column(String(32), server_default="starter")
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MembershipRow(Base):
    __tablename__ = "memberships"

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    roles: Mapped[list[str]] = mapped_column(ARRAY(Text))
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SiteRow(Base):
    __tablename__ = "sites"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(8), server_default="live")
    timezone: Mapped[str] = mapped_column(String(64), server_default="Asia/Kolkata")
    current_model_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SiteModelRow(Base):
    """One version of a site model. Published versions are immutable (a database trigger)."""

    __tablename__ = "site_models"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizations.id"))
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("sites.id"))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB)
    spec_sha256: Mapped[bytes] = mapped_column(LargeBinary)
    validation: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    """The site description this version was generated from, when it came from the builder."""
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def make_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_s,
        pool_pre_ping=True,
        connect_args={
            "timeout": settings.db_pool_timeout_s,
            "server_settings": {"search_path": "pramana"},
        },
    )


CommitListener = Callable[[set[str]], None]


@event.listens_for(Session, "before_flush")
def _track_appended_events(session: Session, _context: Any, _instances: Any) -> None:
    touched = cast(set[str], session.info.setdefault("appended_investigations", set()))
    touched.update(row.investigation_id for row in session.new if isinstance(row, EventRow))


@dataclass
class UnitOfWork:
    db: Database
    session: AsyncSession
    owner_task: asyncio.Task[Any] | None


_unit_of_work: ContextVar[UnitOfWork | None] = ContextVar("unit_of_work", default=None)


class Database:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)
        self.commit_listeners: list[CommitListener] = []
        """Called after a transaction commits, with the investigations it appended events to.
        Used by the event push channel: nothing is announced before it is durable."""

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """One session, one transaction: commits on success, rolls back on any exception."""
        joined = self._joined_session()
        if joined is not None:
            await apply_context(joined)
            yield joined
            await joined.flush()
            return
        async with self._sessions() as session:
            async with session.begin():
                await apply_context(session)
                yield session
                await session.flush()
            # Committed (``begin()`` exited without an exception).
            self._notify(session)

    def _joined_session(self) -> AsyncSession | None:
        work = _unit_of_work.get()
        if work and work.db is self and work.owner_task is asyncio.current_task():
            return work.session
        return None

    def _notify(self, session: AsyncSession) -> None:
        touched = cast(set[str], session.info.get("appended_investigations", set()))
        for listener in list(self.commit_listeners):
            listener(touched)

    @asynccontextmanager
    async def unit_of_work(self) -> AsyncIterator[AsyncSession]:
        """Commit business state and an idempotent response together, then notify readers.

        A child task may inherit organization context, but it never inherits this session.
        """
        if self._joined_session() is not None:
            raise RuntimeError("a request already has a unit of work")
        async with self._sessions() as session:
            async with session.begin():
                token = _unit_of_work.set(UnitOfWork(self, session, asyncio.current_task()))
                try:
                    await apply_context(session)
                    yield session
                    await session.flush()
                finally:
                    _unit_of_work.reset(token)
            self._notify(session)

    @asynccontextmanager
    async def read(self) -> AsyncIterator[AsyncSession]:
        joined = self._joined_session()
        if joined is not None:
            await apply_context(joined)
            yield joined
            return
        async with self._sessions() as session:
            # The session begins a transaction on first use; the context lives until it ends.
            await apply_context(session)
            yield session

    async def ping(self) -> None:
        async with self.engine.connect() as conn:
            await conn.exec_driver_sql("select 1")

    async def require_runtime_role(self) -> None:
        async with self.engine.connect() as conn:
            privileged = (
                await conn.execute(
                    text(
                        "select rolsuper or rolbypassrls from pg_roles where rolname = current_user"
                    )
                )
            ).scalar_one()
        if privileged:
            raise RuntimeError(
                "production must use a non-superuser database role without BYPASSRLS"
            )

    async def dispose(self) -> None:
        await self.engine.dispose()
