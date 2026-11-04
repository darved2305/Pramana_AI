"""Staff accounts and server-side sessions (docs/adr/0010-authentication.md).

The browser holds an opaque random session id in an httpOnly cookie. The database stores only
its SHA-256, so a leaked ``sessions`` table cannot be replayed. Sign-out deletes the row, so a
session ends immediately everywhere (a stateless token could not be revoked like that).
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from pramana_contracts import StaffRole

from ..db import Database, SessionRow, UserRow
from ..errors import ApiError
from .passwords import DUMMY_HASH, hash_password, verify_password


@dataclass(frozen=True)
class Principal:
    """Who is calling. ``kind`` is ``user``, ``automation``, ``participant`` or ``open``
    (sign-in not enforced)."""

    kind: str
    id: str
    display_name: str = ""
    email: str = ""
    roles: frozenset[str] = field(default_factory=frozenset)
    expires_at: datetime | None = None
    participant_id: str | None = None
    scenario_id: str | None = None

    def has(self, role: StaffRole) -> bool:
        return role.value in self.roles


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalise_email(email: str) -> str:
    return email.strip().lower()


class LoginThrottle:
    """Counts failed sign-ins per email in a rolling window (per core process)."""

    def __init__(self, max_failures: int, window_s: float) -> None:
        self.max_failures, self.window_s = max_failures, window_s
        self._fails: dict[str, list[float]] = {}

    def _recent(self, key: str, now: float) -> list[float]:
        kept = [t for t in self._fails.get(key, []) if now - t < self.window_s]
        self._fails[key] = kept
        return kept

    def check(self, key: str, now: float | None = None) -> None:
        if len(self._recent(key, now or time.monotonic())) >= self.max_failures:
            raise ApiError(429, "AUTH_RATE_LIMITED", "too many failed sign-ins; try again later")

    def fail(self, key: str, now: float | None = None) -> None:
        t = now or time.monotonic()
        self._recent(key, t).append(t)

    def clear(self, key: str) -> None:
        self._fails.pop(key, None)


class AuthService:
    def __init__(self, db: Database, ttl_s: int, throttle: LoginThrottle) -> None:
        self.db, self.ttl_s, self.throttle = db, ttl_s, throttle

    async def create_user(
        self, email: str, display_name: str, password: str, roles: list[StaffRole]
    ) -> UserRow:
        if not roles:
            raise ValueError("a user needs at least one role")
        email = normalise_email(email)
        # scrypt is CPU-bound: keep it off the event loop.
        pw_hash = await asyncio.to_thread(hash_password, password)
        async with self.db.transaction() as session:
            existing = (
                await session.execute(select(UserRow).where(UserRow.email == email))
            ).scalar_one_or_none()
            if existing is not None:
                raise ApiError(409, "USER_EXISTS", "a user with that email exists")
            row = UserRow(
                id=f"u_{secrets.token_hex(6)}",
                email=email,
                display_name=display_name,
                password_hash=pw_hash,
                roles=sorted({r.value for r in roles}),
                active=True,
            )
            session.add(row)
        return row

    async def login(self, email: str, password: str) -> tuple[str, Principal]:
        key = normalise_email(email)
        self.throttle.check(key)
        async with self.db.read() as session:
            user = (
                await session.execute(select(UserRow).where(UserRow.email == key))
            ).scalar_one_or_none()
        stored = user.password_hash if user is not None and user.active else DUMMY_HASH
        ok = await asyncio.to_thread(verify_password, password, stored)
        if user is None or not user.active or not ok:
            self.throttle.fail(key)
            # One message for every failure: never reveal whether the account exists.
            raise ApiError(401, "AUTH_INVALID_CREDENTIALS", "email or password is incorrect")
        self.throttle.clear(key)
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=self.ttl_s)
        async with self.db.transaction() as session:
            # Expired sessions are swept opportunistically at sign-in.
            await session.execute(delete(SessionRow).where(SessionRow.expires_at < now))
            session.add(
                SessionRow(
                    token_hash=token_hash(token),
                    user_id=user.id,
                    created_at=now,
                    expires_at=expires,
                )
            )
        return token, self._principal(user, expires)

    async def resolve(self, token: str) -> Principal | None:
        now = datetime.now(UTC)
        async with self.db.read() as session:
            found = (
                await session.execute(
                    select(SessionRow, UserRow)
                    .join(UserRow, UserRow.id == SessionRow.user_id)
                    .where(SessionRow.token_hash == token_hash(token))
                )
            ).one_or_none()
        if found is None:
            return None
        sess, user = found
        if sess.expires_at <= now or not user.active:
            return None
        return self._principal(user, sess.expires_at)

    async def logout(self, token: str) -> None:
        async with self.db.transaction() as session:
            await session.execute(
                delete(SessionRow).where(SessionRow.token_hash == token_hash(token))
            )

    @staticmethod
    def _principal(user: UserRow, expires: datetime) -> Principal:
        return Principal(
            kind="user",
            id=user.id,
            display_name=user.display_name,
            email=user.email,
            roles=frozenset(user.roles),
            expires_at=expires,
        )
