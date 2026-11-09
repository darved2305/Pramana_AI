"""Personal data sealed with one data key per person (PRODUCTION.md 4.6).

Names, reports and transcripts are encrypted with AES-256-GCM under the person's own data key.
Data keys are stored wrapped by a master key. Deleting the wrapped key erases the person: the
ciphertext can no longer be read, while the event log, which holds only ids and outcomes, is
untouched, so replay stays identical.

The master key is held in the process. A Cloud KMS wrapper replaces ``MasterKey`` at deployment;
nothing else here changes.
"""

from __future__ import annotations

import base64
import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy import DateTime, LargeBinary, String, delete, func, select
from sqlalchemy.dialects.postgresql import UUID, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base
from .settings import Settings

ERASED_NAME = "Erased person"
ERASED_REPORT = "This report was erased at the person's request."
SEALED = "-"
"""Stands in for a sealed value in columns and events that must hold something."""

_NONCE = 12


class PersonKeyRow(Base):
    __tablename__ = "person_keys"

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    person_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    wrapped_key: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PersonalTextRow(Base):
    __tablename__ = "personal_texts"

    org_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    investigation_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    item: Mapped[str] = mapped_column(String(64), primary_key=True)
    site_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    person_id: Mapped[str] = mapped_column(String(64))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)


@dataclass(frozen=True)
class PersonRef:
    org_id: uuid.UUID
    site_id: uuid.UUID
    person_id: str

    def context(self, field: str) -> bytes:
        """Binds a ciphertext to its owner, so it cannot be moved onto another person."""
        return f"{self.org_id}/{self.site_id}/{self.person_id}/{field}".encode()


class MasterKey:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("the personal data key must be 32 bytes")
        self._aead = AESGCM(key)

    def wrap(self, data_key: bytes, ref: PersonRef) -> bytes:
        return _seal(self._aead, data_key, ref.context("key"))

    def unwrap(self, wrapped: bytes, ref: PersonRef) -> bytes:
        return _open(self._aead, wrapped, ref.context("key"))

    def seal_response(self, body: bytes, context: bytes) -> bytes:
        return _seal(self._aead, body, b"idempotency-response/" + context)

    def open_response(self, body: bytes, context: bytes) -> bytes:
        return _open(self._aead, body, b"idempotency-response/" + context)


def _seal(aead: AESGCM, plain: bytes, context: bytes) -> bytes:
    nonce = os.urandom(_NONCE)
    return nonce + aead.encrypt(nonce, plain, context)


def _open(aead: AESGCM, blob: bytes, context: bytes) -> bytes:
    return aead.decrypt(blob[:_NONCE], blob[_NONCE:], context)


def master_key(cfg: Settings) -> MasterKey:
    """Production requires its own key (Settings enforces it); elsewhere one is derived."""
    if cfg.pii_master_key is not None:
        value = cfg.pii_master_key.get_secret_value()
        return MasterKey(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
    derived = HKDF(hashes.SHA256(), 32, salt=None, info=b"pramana-dev-personal-data").derive(
        cfg.participant_signing_key.get_secret_value().encode()
    )
    return MasterKey(derived)


class PersonVault:
    def __init__(self, master: MasterKey) -> None:
        self.master = master

    async def data_key(self, session: AsyncSession, ref: PersonRef) -> bytes | None:
        """This person's key, created on first use. ``None`` once they have been erased."""
        await session.execute(
            insert(PersonKeyRow)
            .values(
                org_id=ref.org_id,
                site_id=ref.site_id,
                person_id=ref.person_id,
                wrapped_key=self.master.wrap(AESGCM.generate_key(256), ref),
            )
            .on_conflict_do_nothing()
        )
        wrapped = await session.scalar(
            select(PersonKeyRow.wrapped_key).where(
                PersonKeyRow.org_id == ref.org_id,
                PersonKeyRow.site_id == ref.site_id,
                PersonKeyRow.person_id == ref.person_id,
            )
        )
        return None if wrapped is None else self.master.unwrap(wrapped, ref)

    async def site_keys(
        self, session: AsyncSession, org_id: uuid.UUID, site_id: uuid.UUID
    ) -> dict[str, bytes]:
        """Every readable key at a site. Erased people are simply absent."""
        rows = await session.execute(
            select(PersonKeyRow.person_id, PersonKeyRow.wrapped_key).where(
                PersonKeyRow.org_id == org_id,
                PersonKeyRow.site_id == site_id,
                PersonKeyRow.wrapped_key.is_not(None),
            )
        )
        result: dict[str, bytes] = {}
        for person_id, wrapped in rows.all():
            if wrapped is not None:
                ref = PersonRef(org_id, site_id, person_id)
                result[person_id] = self.master.unwrap(wrapped, ref)
        return result

    @staticmethod
    def encrypt(key: bytes, ref: PersonRef, field: str, text: str) -> bytes:
        return _seal(AESGCM(key), text.encode(), ref.context(field))

    @staticmethod
    def decrypt(key: bytes, ref: PersonRef, field: str, blob: bytes) -> str:
        return _open(AESGCM(key), blob, ref.context(field)).decode()

    async def keep(
        self,
        session: AsyncSession,
        ref: PersonRef,
        *,
        investigation_id: str,
        kind: str,
        item: str,
        text: str,
    ) -> None:
        """Store text belonging to this person. Nothing is stored for someone erased."""
        key = await self.data_key(session, ref)
        if key is None:
            return
        await session.execute(
            insert(PersonalTextRow)
            .values(
                org_id=ref.org_id,
                investigation_id=investigation_id,
                kind=kind,
                item=item,
                site_id=ref.site_id,
                person_id=ref.person_id,
                ciphertext=self.encrypt(key, ref, f"{kind}:{investigation_id}:{item}", text),
            )
            .on_conflict_do_nothing()
        )

    async def texts(
        self, session: AsyncSession, org_id: uuid.UUID, investigation_ids: list[str]
    ) -> dict[tuple[str, str, str], str]:
        """Readable text as ``(investigation, kind, item)``; erased people's text is missing."""
        if not investigation_ids:
            return {}
        rows = (
            await session.execute(
                select(PersonalTextRow, PersonKeyRow.wrapped_key)
                .join(
                    PersonKeyRow,
                    (PersonKeyRow.org_id == PersonalTextRow.org_id)
                    & (PersonKeyRow.site_id == PersonalTextRow.site_id)
                    & (PersonKeyRow.person_id == PersonalTextRow.person_id),
                )
                .where(
                    PersonalTextRow.org_id == org_id,
                    PersonalTextRow.investigation_id.in_(investigation_ids),
                    PersonKeyRow.wrapped_key.is_not(None),
                )
            )
        ).all()
        found: dict[tuple[str, str, str], str] = {}
        for text, wrapped in rows:
            if wrapped is None:
                continue
            ref = PersonRef(text.org_id, text.site_id, text.person_id)
            key = self.master.unwrap(wrapped, ref)
            field = f"{text.kind}:{text.investigation_id}:{text.item}"
            found[(text.investigation_id, text.kind, text.item)] = self.decrypt(
                key, ref, field, text.ciphertext
            )
        return found

    async def erase(self, session: AsyncSession, ref: PersonRef) -> None:
        """Delete the key and the text it protected. The empty key row stays as the tombstone."""
        await session.execute(
            insert(PersonKeyRow)
            .values(
                org_id=ref.org_id,
                site_id=ref.site_id,
                person_id=ref.person_id,
                wrapped_key=None,
                erased_at=datetime.now(UTC),
            )
            .on_conflict_do_update(
                index_elements=["org_id", "site_id", "person_id"],
                set_={
                    "wrapped_key": None,
                    "erased_at": func.coalesce(PersonKeyRow.erased_at, datetime.now(UTC)),
                },
            )
        )
        await session.execute(
            delete(PersonalTextRow).where(
                PersonalTextRow.org_id == ref.org_id,
                PersonalTextRow.site_id == ref.site_id,
                PersonalTextRow.person_id == ref.person_id,
            )
        )
