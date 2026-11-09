"""Drain due invitation email outbox rows once, for a scheduled Cloud Run Job.

Run as the restricted runtime database role, for example:
``uv run python scripts/drain_email_outbox.py``

Cloud Run services also invoke this relay as a response background task. No always-on worker is
required. Repeated runs are safe; a PostgreSQL advisory lock permits only one active relay.
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from pramana_core.db import Database
from pramana_core.mail import GmailSmtp
from pramana_core.outbox import EmailRelay
from pramana_core.settings import Settings


async def run() -> None:
    cfg = Settings()
    db = Database(create_async_engine(cfg.database_url, pool_pre_ping=True))
    try:
        await db.require_runtime_role()
        mailer = (
            GmailSmtp(cfg.gmail_address, cfg.gmail_app_password)
            if cfg.gmail_address and cfg.gmail_app_password
            else None
        )
        result = await EmailRelay(db, mailer).drain()
        print(
            "Email outbox drain: "
            f"locked={result['locked']} sent={result['sent']} "
            f"retried={result['retried']} dead={result['dead']}"
        )
    finally:
        await db.dispose()


if __name__ == "__main__":
    asyncio.run(run())
