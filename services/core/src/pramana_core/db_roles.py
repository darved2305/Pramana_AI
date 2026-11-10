"""Create or harden the least-privilege PostgreSQL runtime roles before Alembic runs.

DATABASE_URL is the migrator connection. DATABASE_RUNTIME_URL and DATABASE_SIMULATOR_URL carry the
``pramana_app`` and ``pramana_sim`` passwords. Values come from the process environment and are
never printed. Passwords reach PostgreSQL only as SCRAM-SHA-256 verifiers computed here, so the
plain text never appears in a statement that server logging could record.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import secrets

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine

ROLES = ("pramana_app", "pramana_sim")
SCRAM_ITERATIONS = 4096


def scram_verifier(password: str, *, salt: bytes | None = None) -> str:
    """The SCRAM-SHA-256 verifier PostgreSQL stores (the same format psql's \\password sends)."""
    salt = salt if salt is not None else secrets.token_bytes(16)
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, SCRAM_ITERATIONS)
    client_key = hmac.digest(salted, b"Client Key", "sha256")
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.digest(salted, b"Server Key", "sha256")

    def b64(value: bytes) -> str:
        return base64.b64encode(value).decode()

    return f"SCRAM-SHA-256${SCRAM_ITERATIONS}:{b64(salt)}${b64(stored_key)}:{b64(server_key)}"


def role_passwords(app_url: str, sim_url: str) -> dict[str, str]:
    app, sim = make_url(app_url), make_url(sim_url)
    if not app.password or not sim.password:
        raise ValueError("runtime database URLs must include their role passwords")
    # The Supabase pooler user name is "<role>.<project ref>".
    if (app.username or "").split(".", 1)[0] != "pramana_app":
        raise ValueError("DATABASE_RUNTIME_URL must connect as pramana_app")
    if (sim.username or "").split(".", 1)[0] != "pramana_sim":
        raise ValueError("DATABASE_SIMULATOR_URL must connect as pramana_sim")
    if app.password == sim.password:
        raise ValueError("core and simulator database passwords must be different")
    return {"pramana_app": app.password, "pramana_sim": sim.password}


def role_statement_template(*, exists: bool) -> str:
    """Use safe creation defaults and audit attributes without requiring superuser rights."""
    action = "alter" if exists else "create"
    return f"{action} role %I login password %L"


async def credentials_work(url: str) -> bool:
    """Avoid replacing an unchanged SCRAM verifier on every deployment."""
    engine = create_async_engine(url, pool_size=1, max_overflow=0)
    try:
        try:
            async with engine.connect() as connection:
                await connection.scalar(text("select 1"))
            return True
        except DBAPIError as exc:
            if getattr(exc.orig, "sqlstate", None) == "28P01":
                return False
            raise
    finally:
        await engine.dispose()


async def ensure_roles(migrator_url: str, app_url: str, sim_url: str) -> None:
    passwords = role_passwords(app_url, sim_url)
    urls = dict(zip(ROLES, (app_url, sim_url), strict=True))
    engine = create_async_engine(migrator_url, pool_size=1, max_overflow=0)
    try:
        async with engine.begin() as connection:
            for role in ROLES:
                exists = await connection.scalar(
                    text("select exists(select 1 from pg_roles where rolname = :role)"),
                    {"role": role},
                )
                if exists and await credentials_work(urls[role]):
                    continue
                statement = await connection.scalar(
                    text(
                        "select format(cast(:template as text), cast(:role as text), "
                        "cast(:verifier as text))"
                    ),
                    {
                        "template": role_statement_template(exists=bool(exists)),
                        "role": role,
                        "verifier": scram_verifier(passwords[role]),
                    },
                )
                await connection.exec_driver_sql(statement)
            unsafe = await connection.execute(
                text(
                    "select rolname from pg_roles where rolname in ('pramana_app', 'pramana_sim') "
                    "and (rolsuper or rolbypassrls or rolcreatedb or rolcreaterole "
                    "or rolreplication)"
                )
            )
            names = [row.rolname for row in unsafe]
            if names:
                raise RuntimeError("runtime database roles remain privileged: " + ", ".join(names))
    finally:
        await engine.dispose()


def main() -> None:
    migrator = os.environ.get("DATABASE_URL")
    app = os.environ.get("DATABASE_RUNTIME_URL")
    sim = os.environ.get("DATABASE_SIMULATOR_URL")
    if not migrator or not app or not sim:
        raise SystemExit(
            "DATABASE_URL, DATABASE_RUNTIME_URL and DATABASE_SIMULATOR_URL are required"
        )
    asyncio.run(ensure_roles(migrator, app, sim))
    print("runtime database roles are least privilege")


if __name__ == "__main__":
    main()
