"""Helpers for selecting a database for schema migrations."""

from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values


def migration_database_url(
    config_url: str | None,
    environment_url: str | None,
    dotenv_path: Path,
) -> str:
    """Resolve an explicit migration URL, refusing every empty or implicit fallback."""
    url = config_url or environment_url
    if not url and dotenv_path.is_file():
        url = dotenv_values(dotenv_path).get("DATABASE_URL")
    if not url or not url.strip():
        raise RuntimeError("DATABASE_URL must explicitly select a database for migrations")
    return url
