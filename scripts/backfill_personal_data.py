"""Seal plaintext site data created before migration 0016.

Run after the schema upgrade and before routing production traffic to the new release:
``uv run python scripts/backfill_personal_data.py --batch-size 100``

Use the schema-owner migration connection and the same PRAMANA_PII_KEY as the core. The command
does not print row values. It is safe to rerun after an interruption; completed rows are skipped.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict

from sqlalchemy.ext.asyncio import create_async_engine

from pramana_core.backfill import backfill_personal_data
from pramana_core.db import Database
from pramana_core.settings import Settings
from pramana_core.vault import PersonVault, master_key


async def run(batch_size: int) -> None:
    cfg = Settings()
    db = Database(create_async_engine(cfg.database_url, pool_pre_ping=True))
    try:
        counts = await backfill_personal_data(
            db, PersonVault(master_key(cfg)), batch_size=batch_size
        )
        summary = ", ".join(f"{name}={count}" for name, count in asdict(counts).items())
        print(f"Personal data backfill complete: {summary}")
    finally:
        await db.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=100)
    options = parser.parse_args()
    asyncio.run(run(options.batch_size))
