"""Shared password-failure windows. Every instance checks the same PostgreSQL rows."""

from __future__ import annotations

import hashlib
import ipaddress
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from ..db import Database, RateLimitRow
from ..errors import ApiError


class PasswordRateLimits:
    def __init__(self, db: Database, max_failures: int, window_s: float):
        self.db, self.max_failures, self.window_s = db, max_failures, window_s

    def _keys(self, email: str, ip: str | None) -> list[tuple[str, str, int]]:
        values = [("password_account", email, self.max_failures)]
        if ip:
            try:
                address = ipaddress.ip_address(ip)
                prefix = ipaddress.ip_network(
                    f"{ip}/{24 if address.version == 4 else 64}", strict=False
                )
                ip = str(prefix)
            except ValueError:
                ip = "unknown"
            values.append(("password_ip", ip, self.max_failures * 10))
        return sorted(
            (scope, hashlib.sha256(key.encode()).hexdigest(), limit) for scope, key, limit in values
        )

    async def check(self, email: str, ip: str | None = None) -> None:
        await self._update(email, ip, None)

    async def failure(self, email: str, ip: str | None = None) -> None:
        await self._update(email, ip, False)

    async def success(self, email: str, ip: str | None = None) -> None:
        await self._update(email, ip, True)

    async def _update(self, email: str, ip: str | None, success: bool | None) -> None:
        now = time.time()
        keys = self._keys(email, ip)
        async with self.db.transaction() as session:
            # Rows from inactive windows need no durable history. No emails or full IPs are stored.
            await session.execute(
                delete(RateLimitRow).where(
                    RateLimitRow.updated_at < datetime.now(UTC) - timedelta(seconds=self.window_s)
                )
            )
            for scope, key, limit in keys:
                await session.execute(
                    insert(RateLimitRow)
                    .values(scope=scope, key_hash=key, failures=[], updated_at=datetime.now(UTC))
                    .on_conflict_do_nothing()
                )
                row = (
                    await session.execute(
                        select(RateLimitRow)
                        .where(RateLimitRow.scope == scope, RateLimitRow.key_hash == key)
                        .with_for_update()
                    )
                ).scalar_one()
                failures = [t for t in row.failures if now - t < self.window_s]
                if len(failures) >= limit:
                    raise ApiError(
                        429, "AUTH_RATE_LIMITED", "too many failed sign-ins; try again later"
                    )
                if success is False:
                    failures.append(now)
                elif success is True and scope == "password_account":
                    failures = []
                row.failures = failures
                row.updated_at = datetime.now(UTC)
