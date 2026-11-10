"""Run a project-local PostgreSQL cluster for development and tests (no Docker needed).

Usage: ``python scripts/dev_db.py {init|start|stop|status}``

The data directory lives outside the repository (default ``%LOCALAPPDATA%/pramana/pgdata`` or
``~/.local/share/pramana/pgdata``) because the repository may sit in a cloud-synced folder, and
syncing a live database directory corrupts it. Authentication is ``trust`` and the server only
listens on localhost; never use this cluster for anything but local development.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PORT = int(os.environ.get("PRAMANA_DB_PORT", "5433"))
USER = "pramana"
DATABASES = tuple(d.strip() for d in os.environ.get("PRAMANA_DB_NAMES", "").split(",") if d.strip())
"""Override with PRAMANA_DB_NAMES, e.g. the production worktree's
``pramana_prod,pramana_prod_test,pramana_prod_e2e``."""
APP_ROLE = "pramana_app"
"""The runtime role: not a superuser and without BYPASSRLS, so row-level security applies to it
(ADR 0015). ``pramana`` stays the owner and runs migrations."""
SIM_ROLE = "pramana_sim"


def data_dir() -> Path:
    env = os.environ.get("PRAMANA_PGDATA")
    if env:
        return Path(env)
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".local" / "share"
    return root / "pramana" / "pgdata"


def pg_bin(tool: str) -> str:
    env = os.environ.get("PG_BIN")
    candidates = [Path(env)] if env else []
    candidates += sorted(Path("C:/Program Files/PostgreSQL").glob("*/bin"), reverse=True)
    for c in candidates:
        for name in (tool, f"{tool}.exe"):
            if (c / name).exists():
                return str(c / name)
    found = shutil.which(tool)
    if found:
        return found
    sys.exit(f"{tool} not found; install PostgreSQL 15+ or set PG_BIN")


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, capture_output=True, text=True)


def is_running() -> bool:
    probe = run(pg_bin("pg_isready"), "-h", "localhost", "-p", str(PORT), check=False)
    return probe.returncode == 0


def init() -> None:
    d = data_dir()
    if (d / "PG_VERSION").exists():
        print(f"cluster already initialised at {d}")
        return
    d.parent.mkdir(parents=True, exist_ok=True)
    run(
        pg_bin("initdb"),
        "-D",
        str(d),
        "-U",
        USER,
        "--auth=trust",
        "--encoding=UTF8",
        "--locale=C",
        "-c",
        "listen_addresses=localhost",
        "-c",
        f"port={PORT}",
    )
    print(f"initialised cluster at {d}")


def start() -> None:
    if not DATABASES or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", db) for db in DATABASES):
        sys.exit("PRAMANA_DB_NAMES must contain comma-separated lowercase database names")
    init()
    if not is_running():
        log = data_dir().parent / "postgres.log"
        # The server inherits pg_ctl's handles; capturing them would block until it exits.
        subprocess.run(
            [pg_bin("pg_ctl"), "-D", str(data_dir()), "-l", str(log), "-w", "start"],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    for db in DATABASES:
        exists = run(
            pg_bin("psql"),
            "-h",
            "localhost",
            "-p",
            str(PORT),
            "-U",
            USER,
            "-d",
            "postgres",
            "-tAc",
            f"select 1 from pg_database where datname='{db}'",
        )
        if exists.stdout.strip() != "1":
            run(pg_bin("createdb"), "-h", "localhost", "-p", str(PORT), "-U", USER, db)
    ensure_app_role()
    print(f"postgres ready on localhost:{PORT} (databases: {', '.join(DATABASES)})")


def ensure_app_role() -> None:
    """Create local test roles once per cluster (additive; existing roles are never altered)."""
    roles = (
        (APP_ROLE, "login nosuperuser nobypassrls nocreatedb nocreaterole"),
        (SIM_ROLE, "login nosuperuser nobypassrls nocreatedb nocreaterole"),
        ("anon", "nologin nosuperuser nobypassrls nocreatedb nocreaterole"),
        ("authenticated", "nologin nosuperuser nobypassrls nocreatedb nocreaterole"),
        ("service_role", "nologin nosuperuser nobypassrls nocreatedb nocreaterole"),
    )
    for name, attributes in roles:
        run(
            pg_bin("psql"),
            "-h",
            "localhost",
            "-p",
            str(PORT),
            "-U",
            USER,
            "-d",
            "postgres",
            "-tAc",
            f"do $$ begin if not exists (select 1 from pg_roles where rolname = '{name}') then "
            f"create role {name} {attributes}; end if; end $$",
        )


def stop() -> None:
    if is_running():
        run(pg_bin("pg_ctl"), "-D", str(data_dir()), "-w", "stop")
    print("postgres stopped")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "init":
        init()
    elif cmd == "start":
        start()
    elif cmd == "stop":
        stop()
    elif cmd == "status":
        print("running" if is_running() else "stopped")
    else:
        sys.exit("usage: dev_db.py {init|start|stop|status}")


if __name__ == "__main__":
    main()
