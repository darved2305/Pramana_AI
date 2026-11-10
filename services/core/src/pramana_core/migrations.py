"""Helpers for selecting a database for schema migrations."""

from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy.engine import make_url


def require_database_name(url: str, setting: str = "DATABASE_URL") -> str:
    """Refuse URLs that would let PostgreSQL infer a user's default database."""
    if not url or not url.strip():
        raise RuntimeError(f"{setting} must explicitly select a database")
    try:
        database = make_url(url).database
    except Exception as exc:
        raise RuntimeError(
            f"{setting} must be a valid PostgreSQL URL with a database name"
        ) from exc
    if not database:
        raise RuntimeError(f"{setting} must include an explicit database name")
    return url


def migration_database_url(
    config_url: str | None,
    environment_url: str | None,
    dotenv_path: Path,
) -> str:
    """Resolve an explicit migration URL, refusing every empty or implicit fallback."""
    url = config_url or environment_url
    if not url and dotenv_path.is_file():
        url = dotenv_values(dotenv_path).get("DATABASE_URL")
    if url is None:
        url = ""
    try:
        return require_database_name(url)
    except RuntimeError as exc:
        raise RuntimeError(
            f"DATABASE_URL must explicitly select a database for migrations: {exc}"
        ) from exc
