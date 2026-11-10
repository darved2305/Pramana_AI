r"""One command for local development: database, migrations, simulator, core (and optionally web).

Usage::

    # Windows PowerShell
    .\.venv\Scripts\python.exe scripts\dev.py [options]

    # POSIX
    uv run python scripts/dev.py [options]

On Windows, run Python directly. If ``uv run`` receives Ctrl-Break, uv can return the Windows
interrupt status ``0xC000013A`` even when this supervisor has stopped every child cleanly.

``make dev`` runs the same thing. Each service runs as a child process whose output is prefixed
with its name. Ctrl+C stops every child: on Windows each child gets its own process group and
receives CTRL_BREAK_EVENT (a console Ctrl+C would not reach a separate group, and killing the
``uv``/``npm`` wrapper alone would orphan the real server); on POSIX each child gets its own
session and the whole group receives SIGTERM. Anything still running after a grace period is
killed.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import IO
from urllib.parse import urlsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def _assign_kill_on_close_job(proc: subprocess.Popen[bytes]) -> int | None:
    """Track a Windows process tree so closing its job cannot leave orphaned children."""
    import ctypes
    from ctypes import wintypes

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_ulonglong)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.INT,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    information = ExtendedLimitInformation()
    information.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job, 9, ctypes.byref(information), ctypes.sizeof(information)
    ) or not kernel32.AssignProcessToJobObject(job, int(proc._handle)):
        kernel32.CloseHandle(job)
        return None
    return int(job)


def _close_job(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    close_handle(handle)


@dataclass(frozen=True)
class Options:
    core_port: int = 8000
    sim_port: int = 8100
    web_port: int = 3002
    web: bool = False
    skip_db: bool = False
    timeout_s: float = 60.0
    demo: bool = False
    oidc_port: int = 8410
    gnani_port: int = 8099


def _port(value: str) -> int:
    port = int(value)
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError(f"port out of range: {value}")
    return port


def parse_args(argv: Sequence[str] | None = None) -> Options:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--demo", action="store_true", help="start the local console with mock sign-in")
    p.add_argument("--oidc-port", type=_port, default=8410)
    p.add_argument("--gnani-port", type=_port, default=8099)
    p.add_argument("--web", action="store_true", help="also start the Next.js dev server")
    p.add_argument("--core-port", type=_port, default=8000)
    p.add_argument("--sim-port", type=_port, default=8100)
    p.add_argument("--web-port", type=_port, default=3002)
    p.add_argument(
        "--skip-db", action="store_true", help="do not start PostgreSQL or run migrations"
    )
    p.add_argument("--timeout", type=float, default=60.0, help="readiness timeout in seconds")
    a = p.parse_args(argv)
    a.web = a.web or a.demo
    ports = [a.core_port, a.sim_port] + ([a.web_port] if a.web else [])
    if a.demo:
        ports.extend([a.oidc_port, a.gnani_port])
    if len(set(ports)) != len(ports):
        p.error(f"ports must differ: {ports}")
    if a.timeout <= 0:
        p.error("--timeout must be positive")
    return Options(
        a.core_port,
        a.sim_port,
        a.web_port,
        a.web,
        a.skip_db,
        a.timeout,
        a.demo,
        a.oidc_port,
        a.gnani_port,
    )


def say(msg: str) -> None:
    print(msg, flush=True)


# -- readiness -------------------------------------------------------------------------------


def http_ok(url: str, timeout_s: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as r:
            return bool(200 <= r.status < 300)
    except (urllib.error.URLError, OSError, ValueError):
        return False


def wait_until(
    check: Callable[[], bool],
    *,
    timeout_s: float,
    alive: Callable[[], bool] = lambda: True,
    interval_s: float = 0.25,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Poll ``check`` until it passes. Gives up early if ``alive`` reports the process died."""
    deadline = clock() + timeout_s
    while True:
        if check():
            return True
        if not alive() or clock() >= deadline:
            return False
        sleep(interval_s)


# -- child processes -------------------------------------------------------------------------


@dataclass
class Child:
    name: str
    args: list[str]
    env: dict[str, str]
    cwd: Path = ROOT
    proc: subprocess.Popen[bytes] | None = None
    _pump: threading.Thread | None = field(default=None, repr=False)
    _stopped: bool = field(default=False, init=False, repr=False)
    _job_handle: int | None = field(default=None, init=False, repr=False)

    def start(self, out: IO[str] | None = None) -> None:
        kwargs: dict[str, object] = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        self.proc = subprocess.Popen(
            self.args,
            cwd=self.cwd,
            env=self.env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            **kwargs,  # type: ignore[call-overload]
        )
        if sys.platform == "win32":
            self._job_handle = _assign_kill_on_close_job(self.proc)
        self._pump = threading.Thread(target=self._relay, args=(out or sys.stdout,), daemon=True)
        self._pump.start()

    def _relay(self, out: IO[str]) -> None:
        assert self.proc is not None
        assert self.proc.stdout is not None
        # Keep draining the child's output whatever happens: if this thread died, the pipe
        # would fill and the child would freeze (Next.js prints a "▲" a Windows console
        # cannot encode, which once left the web server hanging).
        encoding = getattr(out, "encoding", None) or "utf-8"
        for raw in self.proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            text = f"[{self.name}] {line}\n".encode(encoding, "replace").decode(encoding)
            with contextlib.suppress(Exception):
                out.write(text)
                out.flush()

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self, grace_s: float = 8.0) -> None:
        proc = self.proc
        if proc is None or self._stopped:
            return
        self._stopped = True
        try:
            if proc.poll() is None and sys.platform == "win32":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            elif proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
        except (OSError, ValueError):
            pass
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=grace_s)
        if sys.platform == "win32":
            # A cmd wrapper can exit while its node child remains. /T also handles that case.
            with contextlib.suppress(OSError):
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    check=False,
                )
            if self._job_handle is not None:
                _close_job(self._job_handle)
                self._job_handle = None
        else:
            # The group can outlive its leader if a wrapper exits before its children.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
        if proc.poll() is None:
            proc.wait(timeout=5)


def service_env(opts: Options, base: dict[str, str] | None = None) -> dict[str, str]:
    env = {k: v for k, v in dotenv_values(ROOT / ".env").items() if v is not None}
    env.update(os.environ if base is None else base)
    if not env.get("DATABASE_URL", "").strip():
        raise ValueError("DATABASE_URL must explicitly select a database")
    env.update(
        CORE_PORT=str(opts.core_port),
        SIM_PORT=str(opts.sim_port),
        SIM_URL=f"http://127.0.0.1:{opts.sim_port}",
        PRAMANA_CORE_URL=f"http://127.0.0.1:{opts.core_port}",
        PRAMANA_SIM_URL=f"http://127.0.0.1:{opts.sim_port}",
        PYTHONUNBUFFERED="1",
    )
    if opts.demo:
        database = urlsplit(env["DATABASE_URL"])
        if not database.path.strip("/"):
            raise ValueError("DATABASE_URL must include an explicit database name")
        if database.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("demo requires a local database")
        env.update(
            PRAMANA_MODE="dev",
            AUTH_REQUIRED="true",
            SIM_DATABASE_URL="",
            SIM_STATE_FILE="",
            SIM_SERVERLESS_AUTH="false",
            OIDC_ISSUER=f"http://localhost:{opts.oidc_port}",
            OIDC_DISCOVERY_URL=f"http://localhost:{opts.oidc_port}/.well-known/openid-configuration",
            GNANI_API_KEY="local-emulator",
            GNANI_BASE_URL=f"http://127.0.0.1:{opts.gnani_port}",
            GOOGLE_OAUTH_CLIENT_ID="pramana-local",
            GOOGLE_OAUTH_CLIENT_SECRET="local-only",
            OIDC_REDIRECT_URL=f"http://localhost:{opts.web_port}/api/core/v1/auth/google/callback",
            LLM_EXTRACTOR_PROVIDER="none",
            GMAIL_ADDRESS="",
            GMAIL_APP_PASSWORD="",
        )
    origins = [f"http://localhost:{opts.web_port}", "http://localhost:3000"]
    origin_json = "[" + ",".join(f'"{o}"' for o in origins) + "]"
    env.setdefault("CORS_ORIGINS", origin_json)
    env.setdefault("SIM_CORS_ORIGINS", origin_json)
    return env


def children(opts: Options, env: dict[str, str]) -> list[Child]:
    py = sys.executable
    out = [
        Child("sim", [py, "-m", "pramana_sim"], env),
        Child("core", [py, "-m", "pramana_core"], env),
    ]
    if opts.demo:
        out.insert(
            0,
            Child(
                "oidc",
                [py, str(ROOT / "scripts" / "mock_oidc.py"), "--port", str(opts.oidc_port)],
                env,
            ),
        )
        out.insert(
            1,
            Child(
                "gnani-emulator",
                [
                    py,
                    str(ROOT / "scripts" / "gnani_emulator.py"),
                    "--serve",
                    "--port",
                    str(opts.gnani_port),
                ],
                env,
            ),
        )
    if opts.web:
        npm = shutil.which("npm") or "npm"
        out.append(
            Child(
                "web",
                [npm, "run", "dev", "--", "-p", str(opts.web_port)],
                env,
                cwd=ROOT / "apps" / "web",
            )
        )
    return out


def prepare(opts: Options) -> dict[str, str]:
    if not (ROOT / ".env").exists():
        say("[dev] no .env found: generating one with fresh keys (scripts/dev_env.py)")
        subprocess.run([sys.executable, str(ROOT / "scripts" / "dev_env.py")], check=True)
    env = service_env(opts)
    if opts.skip_db:
        return env
    say("[dev] starting PostgreSQL")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "dev_db.py"), "start"], check=True, env=env
    )
    say("[dev] applying migrations")
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT / "services" / "core",
        check=True,
        env=env,
    )
    return env


def _interrupt(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


def main(argv: Sequence[str] | None = None) -> int:
    opts = parse_args(argv)
    # Treat Ctrl+Break (Windows) and SIGTERM like Ctrl+C, so children are always cleaned up.
    for name in ("SIGBREAK", "SIGTERM"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _interrupt)
    procs: list[Child] = []
    try:
        env = prepare(opts)
        procs = children(opts, env)
        checks = {
            "oidc": f"http://127.0.0.1:{opts.oidc_port}/.well-known/openid-configuration",
            "gnani-emulator": f"http://127.0.0.1:{opts.gnani_port}/stats",
            "sim": f"http://127.0.0.1:{opts.sim_port}/health",
            "core": f"http://127.0.0.1:{opts.core_port}/ready",
            "web": f"http://127.0.0.1:{opts.web_port}/",
        }
        for c in procs:
            c.start()
            url = checks[c.name]
            timeout = opts.timeout_s * (3 if c.name == "web" else 1)
            if not wait_until(partial(http_ok, url), timeout_s=timeout, alive=c.alive):
                code = c.proc.poll() if c.proc else None
                say(f"[dev] {c.name} did not become ready ({url}); exit code {code}")
                return 1
            say(f"[dev] {c.name} ready: {url}")
        say(
            "[dev] all services up.\n"
            f"      core  http://127.0.0.1:{opts.core_port}  (docs at /docs)\n"
            f"      sim   http://127.0.0.1:{opts.sim_port}"
            + (f"\n      web   http://localhost:{opts.web_port}" if opts.web else "")
            + "\n      Ctrl+C stops everything."
        )
        if opts.demo:
            say(
                "[dev] Use the local mock sign-in for local@gmail.com, "
                "then start a practice investigation."
            )
        while all(c.alive() for c in procs):
            time.sleep(0.5)
        dead = [c.name for c in procs if not c.alive()]
        say(f"[dev] {', '.join(dead)} exited; stopping the rest")
        return 1
    except KeyboardInterrupt:
        say("\n[dev] stopping")
        return 0
    finally:
        for c in reversed(procs):
            c.stop()


if __name__ == "__main__":
    sys.exit(main())
