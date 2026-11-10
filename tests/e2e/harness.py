"""Real services for end-to-end tests: the simulator and the core as separate OS processes.

Nothing here runs in-process. The session fixture creates (if needed) and re-migrates a
dedicated database, generates fresh keys, starts ``python -m pramana_sim`` and
``python -m pramana_core`` on their own ports, waits for ``/health`` and ``/ready``, and stops
them afterwards. The core can be killed (a hard crash, not a clean shutdown) and restarted, to
test recovery from the event log.

Settings, all optional:

* ``PRAMANA_E2E_DATABASE_URL`` (required; the database it names must be listed in
  ``PRAMANA_DB_NAMES``, see ``scripts/db_guard.py``; there is no default database)
* ``PRAMANA_E2E_CORE_PORT`` (8030) and ``PRAMANA_E2E_SIM_PORT`` (8130)
* ``PRAMANA_SKIP_E2E=1`` skips these tests.

The tests are skipped, with the reason shown, when PostgreSQL is unreachable.
"""

from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

import httpx
from alembic import command
from alembic.config import Config
from db_guard import require_listed_url, setting_database_url
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

ROOT = Path(__file__).resolve().parents[2]
CORE_DIR = ROOT / "services" / "core"
CORE_PORT = int(os.environ.get("PRAMANA_E2E_CORE_PORT", "8030"))
SIM_PORT = int(os.environ.get("PRAMANA_E2E_SIM_PORT", "8130"))


def require_e2e_database_url(url: str | None) -> str:
    if not url:
        raise ValueError(
            "PRAMANA_E2E_DATABASE_URL is not set. Point it at this checkout's "
            "isolated E2E database."
        )
    return url


def e2e_database_url() -> str:
    """The e2e database URL. Refused when unset or when its database is not allowlisted."""
    return require_e2e_database_url(setting_database_url("PRAMANA_E2E_DATABASE_URL"))


@contextmanager
def temporary_work_directory(*, parent: Path | None = None) -> Iterator[Path]:
    """Create an e2e work directory that is removed after the fixture finishes.

    On Windows a killed service's grandchild (uv starts the Python process) can keep its log file
    open for a moment after the tree kill returns, so removal retries briefly before giving up.
    """
    directory = Path(tempfile.mkdtemp(prefix="pramana-e2e-", dir=parent))
    try:
        yield directory
    finally:
        for attempt in range(50):
            try:
                shutil.rmtree(directory)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(0.2)


async def ensure_database(url: str) -> None:
    """Create the e2e database if it is missing (connects to the server's ``postgres`` db)."""
    require_listed_url(url)
    target = make_url(url)
    admin = create_async_engine(
        target.set(database="postgres"), isolation_level="AUTOCOMMIT", connect_args={"timeout": 3}
    )
    try:
        async with admin.connect() as conn:
            exists = await conn.execute(
                text("select 1 from pg_database where datname = :d"), {"d": target.database}
            )
            if exists.scalar() is None:
                await conn.exec_driver_sql(f'create database "{target.database}"')
    finally:
        await admin.dispose()


def migrate(url: str) -> None:
    cfg = Config(str(CORE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(CORE_DIR / "alembic"))
    cfg.attributes["url"] = require_listed_url(url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


@dataclass
class Process:
    name: str
    args: list[str]
    env: dict[str, str]
    cwd: Path
    log_path: Path
    proc: subprocess.Popen[bytes] | None = None
    _log: IO[bytes] | None = field(default=None, repr=False)

    def start(self) -> None:
        kwargs: dict[str, object] = {}
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        self._log = self.log_path.open("ab")
        self.proc = subprocess.Popen(  # fixed argument list
            self.args,
            cwd=self.cwd,
            env=self.env,
            stdin=subprocess.DEVNULL,
            stdout=self._log,
            stderr=subprocess.STDOUT,
            **kwargs,  # type: ignore[call-overload]
        )

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def kill(self) -> None:
        """A crash: no shutdown handlers, no flushing, nothing graceful."""
        try:
            if self.proc is not None:
                if os.name == "nt":
                    if self.proc.poll() is None:
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                            capture_output=True,
                            check=False,
                        )
                else:
                    with suppress(ProcessLookupError):
                        os.killpg(self.proc.pid, signal.SIGKILL)
                if self.proc.poll() is None:
                    self.proc.wait(timeout=10)
        finally:
            if self._log is not None:
                self._log.close()
                self._log = None

    def tail(self, n: int = 40) -> str:
        try:
            lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except FileNotFoundError:
            return ""
        return "\n".join(lines[-n:])


@dataclass
class Services:
    core_url: str
    sim_url: str
    signing_key: str
    operator_key: str
    oracle_key: str
    sim: Process
    core: Process
    automation_key: str = ""
    """The core enforces sign-in (docs/adr/0010); the harness acts through the automation key."""

    def wait_ready(self, proc: Process, url: str, timeout_s: float = 60.0) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if not proc.alive():
                raise RuntimeError(f"{proc.name} exited early:\n{proc.tail()}")
            try:
                if httpx.get(url, timeout=2).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise RuntimeError(f"{proc.name} not ready at {url}:\n{proc.tail()}")

    def crash_core(self) -> None:
        self.core.kill()

    def restart_core(self) -> None:
        self.core.kill()
        self.core.start()
        self.wait_ready(self.core, f"{self.core_url}/ready")

    def client(self, base: str) -> httpx.Client:
        headers = (
            {"X-Automation-Key": self.automation_key}
            if base == self.core_url and self.automation_key
            else {}
        )
        return httpx.Client(base_url=base, timeout=30, headers=headers)
