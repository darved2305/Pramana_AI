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

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pramana_contracts import StaffRole

from .. import ids
from ..db import Database, SessionRow, UserRow
from ..errors import ApiError
from .passwords import DUMMY_HASH, hash_password, verify_password
from .rate_limits import PasswordRateLimits


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
    email_verified: bool = False
    auth_method: str | None = None
    hosted_domain: str | None = None
    authenticated_at: datetime | None = None
    organization_id: str | None = None
    token_id: str | None = None

    def has(self, role: StaffRole) -> bool:
        return role.value in self.roles


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalise_email(email: str) -> str:
    return email.strip().lower()


class LoginThrottle:
    """Legacy window/configuration interface. AuthService enforces shared PostgreSQL windows."""

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
    def __init__(
        self, db: Database, ttl_s: int, throttle: LoginThrottle, *, idle_s: int = 3600
    ) -> None:
        self.db, self.ttl_s, self.throttle = db, ttl_s, throttle
        self.idle_s = min(idle_s, ttl_s)
        self.rate_limits = PasswordRateLimits(db, throttle.max_failures, throttle.window_s)

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
                await session.execute(select(UserRow).where(func.lower(UserRow.email) == email))
            ).scalar_one_or_none()
            if existing is not None:
                raise ApiError(409, "USER_EXISTS", "a user with that email exists")
            row = UserRow(
                id=ids.new("usr")[1],
                email=email,
                display_name=display_name,
                password_hash=pw_hash,
                roles=sorted({r.value for r in roles}),
                active=True,
                email_verified_at=datetime.now(UTC),
            )
            session.add(row)
        return row

    async def login(
        self,
        email: str,
        password: str,
        *,
        old_token: str | None = None,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> tuple[str, Principal]:
        key = normalise_email(email)
        await self.rate_limits.check(key, ip)
        async with self.db.read() as session:
            user = (
                await session.execute(select(UserRow).where(func.lower(UserRow.email) == key))
            ).scalar_one_or_none()
        stored = (
            user.password_hash
            if user is not None and user.active and user.password_hash
            else DUMMY_HASH
        )
        ok = await asyncio.to_thread(verify_password, password, stored)
        if user is None or not user.active or user.password_hash is None or not ok:
            await self.rate_limits.failure(key, ip)
            # One message for every failure: never reveal whether the account exists.
            raise ApiError(401, "AUTH_INVALID_CREDENTIALS", "email or password is incorrect")
        await self.rate_limits.success(key, ip)
        async with self.db.transaction() as session:
            current = (
                await session.execute(
                    select(UserRow).where(UserRow.id == user.id).with_for_update()
                )
            ).scalar_one_or_none()
            if current is None or not current.active or current.password_hash != stored:
                raise ApiError(401, "AUTH_INVALID_CREDENTIALS", "email or password is incorrect")
            if old_token:
                await session.execute(
                    delete(SessionRow).where(SessionRow.token_hash == token_hash(old_token))
                )
            return await self.issue_session(
                session, current, auth_method="password", user_agent=user_agent
            )

    async def issue_session(
        self,
        session: AsyncSession,
        user: UserRow,
        *,
        auth_method: str,
        user_agent: str | None = None,
        hosted_domain: str | None = None,
    ) -> tuple[str, Principal]:
        token = secrets.token_urlsafe(32)
        now = datetime.now(UTC)
        absolute = now + timedelta(seconds=min(self.ttl_s, 12 * 3600))
        idle = min(absolute, now + timedelta(seconds=self.idle_s))
        await session.execute(
            delete(SessionRow).where(
                or_(
                    SessionRow.expires_at <= now,
                    SessionRow.absolute_expires_at <= now,
                    SessionRow.idle_expires_at <= now,
                )
            )
        )
        session.add(
            SessionRow(
                token_hash=token_hash(token),
                user_id=user.id,
                created_at=now,
                expires_at=absolute,
                last_seen_at=now,
                absolute_expires_at=absolute,
                idle_expires_at=idle,
                auth_method=auth_method,
                hosted_domain=hosted_domain if auth_method == "google" else None,
                user_agent=user_agent[:512] if user_agent else None,
            )
        )
        return token, self._principal(
            user,
            idle,
            auth_method=auth_method,
            hosted_domain=hosted_domain,
            authenticated_at=now,
        )

    async def resolve(self, token: str, *, touch: bool = True) -> Principal | None:
        if len(token) > 256:
            return None
        now = datetime.now(UTC)
        async with self.db.transaction() as session:
            found = (
                await session.execute(
                    select(SessionRow, UserRow)
                    .join(UserRow, UserRow.id == SessionRow.user_id)
                    .where(SessionRow.token_hash == token_hash(token))
                    .with_for_update(of=SessionRow)
                )
            ).one_or_none()
            if found is None:
                return None
            sess, user = found
            deadline = min(sess.expires_at, sess.absolute_expires_at, sess.idle_expires_at)
            if deadline <= now or not user.active:
                return None
            if touch:
                sess.last_seen_at = now
                sess.idle_expires_at = min(
                    sess.expires_at, sess.absolute_expires_at, now + timedelta(seconds=self.idle_s)
                )
                deadline = sess.idle_expires_at
            return self._principal(
                user,
                deadline,
                auth_method=sess.auth_method,
                hosted_domain=sess.hosted_domain,
                authenticated_at=sess.created_at,
            )

    async def logout(self, token: str) -> None:
        async with self.db.transaction() as session:
            await session.execute(
                delete(SessionRow).where(SessionRow.token_hash == token_hash(token))
            )

    async def devices(self, user_id: str) -> list[SessionRow]:
        now = datetime.now(UTC)
        async with self.db.read() as session:
            rows = await session.scalars(
                select(SessionRow)
                .where(
                    SessionRow.user_id == user_id,
                    SessionRow.idle_expires_at > now,
                    SessionRow.absolute_expires_at > now,
                    SessionRow.expires_at > now,
                )
                .order_by(SessionRow.last_seen_at.desc())
            )
            return list(rows)

    async def revoke_others(self, user_id: str, current_token: str) -> None:
        async with self.db.transaction() as session:
            await session.execute(
                delete(SessionRow).where(
                    SessionRow.user_id == user_id,
                    SessionRow.token_hash != token_hash(current_token),
                )
            )

    async def revoke_device(self, user_id: str, device_id: str) -> None:
        async with self.db.transaction() as session:
            await session.execute(
                delete(SessionRow).where(
                    SessionRow.user_id == user_id, SessionRow.token_hash == device_id
                )
            )

    @staticmethod
    def _principal(
        user: UserRow,
        expires: datetime,
        *,
        auth_method: str | None = None,
        hosted_domain: str | None = None,
        authenticated_at: datetime | None = None,
    ) -> Principal:
        return Principal(
            kind="user",
            id=user.id,
            display_name=user.display_name,
            email=user.email,
            roles=frozenset(user.roles) if user.email_verified_at else frozenset(),
            expires_at=expires,
            email_verified=user.email_verified_at is not None,
            auth_method=auth_method,
            hosted_domain=hosted_domain if auth_method == "google" else None,
            authenticated_at=authenticated_at,
        )
