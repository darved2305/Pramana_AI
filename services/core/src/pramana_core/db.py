"""Persistence: an append-only event log plus read projections, on PostgreSQL.

Events are the source of truth for rebuilding an investigation's engine. Projections
(``investigations``, ``questions``, ``observations``) exist for queries and are written in the
same transaction as the events that produce them. One ``AsyncSession`` is created per unit of
work and never shared between concurrent tasks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any, ClassVar

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .settings import Settings


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSONB}


class InvestigationRow(Base):
    __tablename__ = "investigations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    pack_id: Mapped[str] = mapped_column(String(64))
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


class EventRow(Base):
    __tablename__ = "events"

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    investigation_id: Mapped[str] = mapped_column(
        ForeignKey("investigations.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("events_inv_seq", "investigation_id", "seq"),)


class QuestionRow(Base):
    __tablename__ = "questions"

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
    asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ObservationRow(Base):
    __tablename__ = "observations"

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
    approver_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    capability_jti: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    """Only one capability is ever minted per approval."""


class VoiceUsageRow(Base):
    """One metered Gnani call: billable units (audio seconds or characters) and priced cost."""

    __tablename__ = "voice_usage"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    service: Mapped[str] = mapped_column(String(16))
    units: Mapped[float] = mapped_column(Float)
    cost_inr: Mapped[float] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def make_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_s,
        pool_pre_ping=True,
        connect_args={"timeout": settings.db_pool_timeout_s},
    )


class Database:
    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine
        self._sessions = async_sessionmaker(engine, expire_on_commit=False)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncSession]:
        """One session, one transaction: commits on success, rolls back on any exception."""
        async with self._sessions() as session, session.begin():
            yield session

    @asynccontextmanager
    async def read(self) -> AsyncIterator[AsyncSession]:
        async with self._sessions() as session:
            yield session

    async def ping(self) -> None:
        async with self.engine.connect() as conn:
            await conn.exec_driver_sql("select 1")

    async def dispose(self) -> None:
        await self.engine.dispose()
