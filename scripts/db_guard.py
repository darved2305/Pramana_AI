"""Allowlist guard for every command that resets a database.

A reset (migrations down to base, truncating tables) runs only against a database URL that is
given explicitly and names a database listed in ``PRAMANA_DB_NAMES``. Both values are read from
the process environment first and then from this checkout's ``.env``. Nothing has a default
database: a checkout whose settings did not load refuses, instead of resetting a database that
belongs to another checkout on the shared local cluster.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class DatabaseGuardError(RuntimeError):
    """A reset was refused. The message names the setting or the database."""


def _setting(name: str, environ: Mapping[str, str] | None, dotenv_path: Path | None) -> str:
    value = (os.environ if environ is None else environ).get(name, "").strip()
    if not value and dotenv_path is not None and dotenv_path.is_file():
        value = (dotenv_values(dotenv_path).get(name) or "").strip()
    return value


def listed_databases(
    environ: Mapping[str, str] | None = None, dotenv_path: Path | None = ENV_FILE
) -> frozenset[str]:
    names = _setting("PRAMANA_DB_NAMES", environ, dotenv_path)
    return frozenset(entry.strip() for entry in names.split(",") if entry.strip())


def require_listed_database(
    name: str,
    *,
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path | None = ENV_FILE,
) -> str:
    """Return ``name`` only if it is listed in ``PRAMANA_DB_NAMES``."""
    allowed = listed_databases(environ, dotenv_path)
    if not allowed:
        raise DatabaseGuardError("refusing to reset a database: PRAMANA_DB_NAMES is not set")
    if not name or name not in allowed:
        raise DatabaseGuardError(
            f"refusing to reset database {name!r}: it is not listed in PRAMANA_DB_NAMES"
        )
    return name


def require_listed_url(
    url: str,
    *,
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path | None = ENV_FILE,
) -> str:
    """Return ``url`` only if the database it names is listed in ``PRAMANA_DB_NAMES``."""
    if not url.strip():
        raise DatabaseGuardError("refusing to reset a database: the database URL is empty")
    require_listed_database(
        urlsplit(url).path.lstrip("/"), environ=environ, dotenv_path=dotenv_path
    )
    return url


def setting_database_url(
    setting: str,
    *,
    environ: Mapping[str, str] | None = None,
    dotenv_path: Path | None = ENV_FILE,
) -> str:
    """Return the URL held by ``setting``, refusing when it is unset or not allowlisted."""
    url = _setting(setting, environ, dotenv_path)
    if not url:
        raise DatabaseGuardError(f"refusing to reset a database: {setting} is not set")
    return require_listed_url(url, environ=environ, dotenv_path=dotenv_path)
