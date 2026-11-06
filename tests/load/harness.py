"""Process-level emulated voice load harness for Pramana."""

from __future__ import annotations

import asyncio
import contextlib
import ctypes
import json
import math
import os
import re
import secrets
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import websockets
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from pramana_contracts.tokens import (
    generate_private_key_b64,
    private_key_from_b64,
    public_key_b64,
)

ROOT = Path(__file__).resolve().parents[2]
CORE_DIR = ROOT / "services" / "core"
FAKE_SERVER = ROOT / "tests" / "load" / "fake_gnani_server.py"
DEFAULT_SCRATCH = Path(r"C:\Users\Nikhil\pramana-orch\scratch\FIX-P3-r1")
RSS_SAMPLE_INTERVAL_S = 5.0
RSS_SLOPE_LIMIT_MIB_PER_MIN = 1.0
RSS_GROWTH_LIMIT_MIB = 32.0
CAP_PROBE_STREAM_LIMIT = 2
ALLOWED_CALL_CLOSE_CODES = {1000, 4408}
ALLOWED_PROVIDER_CLOSE_CODES = {1000}
MAX_CALL_HANDOFF_GAP_S = 2.0
MAX_CALL_HANDOFF_GAP_RATIO = 0.01
MAX_PARALLEL_BOT_RUNS = 3
MAX_PARALLEL_CALL_SOCKETS = MAX_PARALLEL_BOT_RUNS * 3
HANDOFF_REPLENISH_AT_CALL_COUNT = 5


@dataclass(frozen=True)
class LoadOptions:
    duration_s: float
    database_url: str
    scratch_root: Path = DEFAULT_SCRATCH
    report_dir: Path | None = None
    core_port: int = 8210
    sim_port: int = 8110
    fake_port: int = 8310
    stream_cap: int = 16
    live: bool = False
    clips: Path | None = None
    test_local_provider: bool = False


def _should_launch_handoff_run(*, running_jobs: int, active_call_sockets: int) -> bool:
    """Start a third run early enough for its calls to open before the next handoff."""
    return running_jobs < MAX_PARALLEL_BOT_RUNS and (
        active_call_sockets <= HANDOFF_REPLENISH_AT_CALL_COUNT or running_jobs == 1
    )


class ManagedProcess:
    """One real service process with logs captured below the task scratch directory."""

    def __init__(
        self,
        name: str,
        args: list[str],
        env: dict[str, str],
        log_path: Path,
    ) -> None:
        self.name = name
        self.args = args
        self.env = env
        self.log_path = log_path
        self.process: subprocess.Popen[bytes] | None = None
        self._log_file: Any = None

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            raise RuntimeError(f"{self.name} is already running")
        self._log_file = self.log_path.open("ab")
        options: dict[str, Any] = {}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        self.process = subprocess.Popen(
            self.args,
            cwd=ROOT,
            env=self.env,
            stdin=subprocess.DEVNULL,
            stdout=self._log_file,
            stderr=subprocess.STDOUT,
            **options,
        )

    @property
    def pid(self) -> int:
        if self.process is None:
            raise RuntimeError(f"{self.name} has not been started")
        return self.process.pid

    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self) -> None:
        process = self.process
        if process is not None and process.poll() is None:
            try:
                if os.name == "nt":
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(process.pid, signal.SIGTERM)
            except (OSError, ValueError):
                pass
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                        capture_output=True,
                        check=False,
                    )
                else:
                    os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    def tail(self, count: int = 60) -> str:
        try:
            lines = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except FileNotFoundError:
            return ""
        return "\n".join(lines[-count:])


class BotProcess:
    """One concurrent voice-bot investigation with isolated log and socket-event files."""

    def __init__(self, name: str, log_path: Path, aggregate_log: Path) -> None:
        self.name = name
        self.log_path = log_path
        self.aggregate_log = aggregate_log
        self.process: asyncio.subprocess.Process | None = None
        self._log_file: Any = None
        self._result: dict[str, Any] | None = None
        self.started_at: float | None = None

    async def start(self, args: list[str], env: dict[str, str]) -> None:
        if self.process is not None:
            raise RuntimeError(f"{self.name} has already started")
        self._log_file = self.log_path.open("wb")
        options: dict[str, Any] = {}
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        self.process = await asyncio.create_subprocess_exec(
            *args,
            cwd=ROOT,
            env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=self._log_file,
            stderr=asyncio.subprocess.STDOUT,
            **options,
        )
        self.started_at = time.monotonic()

    @property
    def returncode(self) -> int | None:
        return self.process.returncode if self.process is not None else None

    async def stop(self) -> None:
        process = self.process
        if process is not None and process.returncode is None:
            try:
                if os.name == "nt":
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(process.pid, signal.SIGTERM)
            except (OSError, ValueError):
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=8)
            except TimeoutError:
                process.kill()
                await asyncio.wait_for(process.wait(), timeout=5)
        self._close_log()

    def _close_log(self) -> None:
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    async def result(self) -> dict[str, Any]:
        if self.process is None:
            raise RuntimeError(f"{self.name} has not started")
        returncode = await self.process.wait()
        self._close_log()
        try:
            output = self.log_path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            output = ""
        with self.aggregate_log.open("a", encoding="utf-8") as aggregate:
            aggregate.write(f"\n--- {self.name} ---\n")
            aggregate.write(output)
        if self._result is not None:
            return self._result
        self._result = _parse_bot_result(output, returncode)
        return self._result


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def _validate_options(options: LoadOptions) -> None:
    if options.duration_s <= 0:
        raise ValueError("load duration must be positive")
    if not 1 <= options.stream_cap <= 20:
        raise ValueError("stream cap must be between 1 and 20")
    if options.live and (options.clips is None or not options.clips.is_dir()):
        raise ValueError("live mode requires --clips pointing to 16 kHz mono PCM16 samples")
    if options.test_local_provider and not options.live:
        raise ValueError("the local provider stand-in is only for exercising live-mode handling")
    if options.live and options.report_dir is not None:
        raise ValueError("live runs cannot write metrics into eval reports")
    if not options.live and options.report_dir is None and options.duration_s >= 600:
        raise ValueError("the full emulated run requires a report directory")
    for port in (options.core_port, options.sim_port):
        if not 1 <= port <= 65535:
            raise ValueError(f"port out of range: {port}")
    if options.core_port == options.sim_port:
        raise ValueError("core and simulator ports must differ")
    if not options.live:
        if not 1 <= options.fake_port <= 65535:
            raise ValueError(f"port out of range: {options.fake_port}")
        if options.fake_port in (options.core_port, options.sim_port):
            raise ValueError("fake provider port must differ from core and simulator ports")


def _ensure_postgres_and_database(database_url: str, env: dict[str, str]) -> None:
    start = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "dev_db.py"), "start"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if start.returncode != 0:
        raise RuntimeError(f"PostgreSQL start failed: {start.stdout}\n{start.stderr}")

    target = make_url(database_url)
    if target.get_backend_name() != "postgresql":
        raise ValueError("load database URL must use PostgreSQL")
    if target.host not in ("localhost", "127.0.0.1") or target.port != 5433:
        raise ValueError("load database must use the shared PostgreSQL cluster at localhost:5433")
    if not target.database or not re.fullmatch(
        r"pramana_load_fa31(?:_[a-z0-9]+)?", target.database
    ):
        raise ValueError("load database name must start with pramana_load_fa31")

    pg_bin = Path(env.get("PG_BIN", r"C:\Users\Nikhil\scoop\apps\postgresql\current\bin"))
    psql = pg_bin / ("psql.exe" if os.name == "nt" else "psql")
    createdb = pg_bin / ("createdb.exe" if os.name == "nt" else "createdb")
    if not psql.exists() or not createdb.exists():
        psql = Path(shutil.which("psql") or "psql")
        createdb = Path(shutil.which("createdb") or "createdb")
    user = target.username or "pramana"
    check = subprocess.run(
        [
            str(psql),
            "-h",
            target.host,
            "-p",
            str(target.port),
            "-U",
            user,
            "-d",
            "postgres",
            "-t",
            "-A",
            "-c",
            f"SELECT 1 FROM pg_database WHERE datname = '{target.database}'",
        ],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if check.returncode != 0:
        raise RuntimeError(f"PostgreSQL database check failed: {check.stderr}")
    if check.stdout.strip() != "1":
        created = subprocess.run(
            [
                str(createdb),
                "-h",
                target.host,
                "-p",
                str(target.port),
                "-U",
                user,
                target.database,
            ],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if created.returncode != 0:
            raise RuntimeError(f"Could not create {target.database}: {created.stderr}")

    config = Config(str(CORE_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(CORE_DIR / "alembic"))
    config.attributes["url"] = database_url
    command.upgrade(config, "head")


def _load_key_configured() -> bool:
    if os.environ.get("GNANI_API_KEY", "").strip():
        return True
    try:
        from pramana_core.llm import read_env_file

        return bool(read_env_file(ROOT / ".env").get("GNANI_API_KEY", "").strip())
    except (OSError, ValueError):
        return False


def _environment(
    *,
    options: LoadOptions,
    run_dir: Path,
    signing_key: str,
    operator_key: str,
    oracle_key: str,
    automation_key: str,
    public_key: str,
    fake_url: str | None,
    stream_cap: int,
) -> tuple[dict[str, str], dict[str, str]]:
    base = os.environ.copy()
    base["PYTHONIOENCODING"] = "utf-8"
    base["PYTHONUNBUFFERED"] = "1"
    path_parts = [str(ROOT / "scripts")]
    if base.get("PYTHONPATH"):
        path_parts.append(base["PYTHONPATH"])
    base["PYTHONPATH"] = os.pathsep.join(path_parts)

    sim_env = base.copy()
    sim_env.update(
        {
            "SIM_PORT": str(options.sim_port),
            "SIM_OPERATOR_KEY": operator_key,
            "SIM_ORACLE_KEY": oracle_key,
            "SIM_PARTICIPANT_PUBLIC_KEY": public_key,
            "SIM_CORS_ORIGINS": "[]",
        }
    )

    core_env = base.copy()
    core_env.update(
        {
            "PRAMANA_MODE": "dev",
            "CORE_HOST": "127.0.0.1",
            "CORE_PORT": str(options.core_port),
            "DATABASE_URL": options.database_url,
            "DB_POOL_SIZE": "5",
            "DB_MAX_OVERFLOW": "2",
            "SIM_URL": f"http://127.0.0.1:{options.sim_port}",
            "SIM_OPERATOR_KEY": operator_key,
            "PARTICIPANT_SIGNING_KEY": signing_key,
            "CORE_AUTOMATION_KEY": automation_key,
            "LLM_EXTRACTOR_PROVIDER": "none",
            "LLM_CACHE_DIR": str(run_dir / "llm"),
            "TTS_CACHE_DIR": str(run_dir / "tts"),
            "GNANI_MAX_STREAMS": str(stream_cap),
            "VOICE_DAILY_BUDGET_INR": "150",
            "LOG_JSON": "true",
            "LOG_LEVEL": "INFO",
            "CORS_ORIGINS": "[]",
        }
    )
    if fake_url is not None:
        core_env["GNANI_API_KEY"] = "local-p3-emulator"
        core_env["GNANI_BASE_URL"] = fake_url
        core_env["GNANI_TIMEOUT_S"] = "10"
    return sim_env, core_env


def _wait_http(process: ManagedProcess, url: str, timeout_s: float = 45.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not process.alive():
            raise RuntimeError(f"{process.name} exited before readiness:\n{process.tail()}")
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                if 200 <= response.status < 300:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.2)
    raise RuntimeError(f"{process.name} did not become ready at {url}:\n{process.tail()}")


def _process_tree_pids(root_pid: int, parent_by_pid: dict[int, int]) -> list[int]:
    """Return a launched process and every descendant, including worker interpreters."""
    children: dict[int, list[int]] = {}
    for child_pid, parent_pid in parent_by_pid.items():
        children.setdefault(parent_pid, []).append(child_pid)
    result = [root_pid]
    index = 0
    while index < len(result):
        result.extend(children.get(result[index], ()))
        index += 1
    return result


def _windows_process_tree_pids(root_pid: int) -> list[int]:
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.Process32FirstW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    kernel.Process32FirstW.restype = wintypes.BOOL
    kernel.Process32NextW.argtypes = (wintypes.HANDLE, ctypes.POINTER(ProcessEntry))
    kernel.Process32NextW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    snapshot = kernel.CreateToolhelp32Snapshot(0x00000002, 0)
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        return [root_pid]
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(ProcessEntry)
        parents: dict[int, int] = {}
        if kernel.Process32FirstW(snapshot, ctypes.byref(entry)):
            while True:
                parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                if not kernel.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
        return _process_tree_pids(root_pid, parents)
    finally:
        kernel.CloseHandle(snapshot)


def _windows_process_snapshot(pid: int) -> dict[str, int | None]:
    from ctypes import wintypes

    class MemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.GetProcessHandleCount.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    kernel.GetProcessHandleCount.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(MemoryCounters),
        wintypes.DWORD,
    )
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return {"rss_bytes": None, "handles": None}
    try:
        memory = MemoryCounters()
        memory.cb = ctypes.sizeof(memory)
        handle_count = wintypes.DWORD()
        ok_memory = psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb)
        ok_handles = kernel.GetProcessHandleCount(handle, ctypes.byref(handle_count))
        return {
            "rss_bytes": int(memory.WorkingSetSize) if ok_memory else None,
            "handles": int(handle_count.value) if ok_handles else None,
        }
    finally:
        kernel.CloseHandle(handle)


def _process_snapshot(pid: int) -> dict[str, int | None]:
    if os.name == "nt":
        snapshots = [_windows_process_snapshot(item) for item in _windows_process_tree_pids(pid)]
        rss = [int(item["rss_bytes"]) for item in snapshots if item["rss_bytes"] is not None]
        handles = [int(item["handles"]) for item in snapshots if item["handles"] is not None]
        return {
            "rss_bytes": sum(rss) if rss else None,
            "handles": sum(handles) if handles else None,
        }
    if sys.platform.startswith("linux"):
        try:
            status = (Path("/proc") / str(pid) / "status").read_text(encoding="ascii")
            rss_kib = next(
                int(line.split()[1]) for line in status.splitlines() if line.startswith("VmRSS:")
            )
            handles = len(list((Path("/proc") / str(pid) / "fd").iterdir()))
            return {"rss_bytes": rss_kib * 1024, "handles": handles}
        except (OSError, StopIteration, ValueError):
            pass
    return {"rss_bytes": None, "handles": None}


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(ordered[lower], 3)
    fraction = position - lower
    return round(ordered[lower] * (1 - fraction) + ordered[upper] * fraction, 3)


def _rss_summary(samples: list[dict[str, Any]], key: str) -> dict[str, Any]:
    points = [
        (float(sample["elapsed_seconds"]) / 60, int(sample[key]))
        for sample in samples
        if sample.get(key) is not None
    ]
    if not points:
        return {
            "samples": 0,
            "start_mib": None,
            "end_mib": None,
            "growth_mib": None,
            "slope_mib_per_min": None,
        }
    x_mean = statistics.mean(x for x, _ in points)
    y_mean = statistics.mean(y for _, y in points)
    denominator = sum((x - x_mean) ** 2 for x, _ in points)
    slope = (
        sum((x - x_mean) * (y - y_mean) for x, y in points) / denominator
        if denominator > 0
        else 0.0
    )
    mib = 1024 * 1024
    return {
        "samples": len(points),
        "start_mib": round(points[0][1] / mib, 3),
        "end_mib": round(points[-1][1] / mib, 3),
        "growth_mib": round((points[-1][1] - points[0][1]) / mib, 3),
        "slope_mib_per_min": round(slope / mib, 4),
    }


def _structured_events(log_path: Path, event_name: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        return events
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("event") == event_name:
            events.append(record)
    return events


def _call_close_issues(
    client_closes: list[dict[str, Any]], core_closes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Correlate call close frames and lifecycle events by the server call-session ID."""
    issues: list[dict[str, Any]] = []
    client_by_id: dict[str, list[dict[str, Any]]] = {}
    core_by_id: dict[str, list[dict[str, Any]]] = {}
    for side, events, target in (
        ("participant_client", client_closes, client_by_id),
        ("participant_core", core_closes, core_by_id),
    ):
        for event in events:
            session_id = str(event.get("call_session_id") or "")
            if not session_id:
                issues.append({"side": side, "issue": "missing call session ID", **event})
                continue
            target.setdefault(session_id, []).append(event)
        for session_id, matches in target.items():
            if len(matches) > 1:
                issues.append(
                    {
                        "side": side,
                        "call_session_id": session_id,
                        "issue": "duplicate close event",
                    }
                )

    for session_id in sorted(set(client_by_id) | set(core_by_id)):
        client_matches = client_by_id.get(session_id, [])
        core_matches = core_by_id.get(session_id, [])
        if len(client_matches) != 1 or len(core_matches) != 1:
            missing_side = "participant_client" if not client_matches else "participant_core"
            if not client_matches or not core_matches:
                issues.append(
                    {
                        "side": missing_side,
                        "call_session_id": session_id,
                        "issue": "call close is missing on one side",
                    }
                )
            continue
        client = client_matches[0]
        core = core_matches[0]
        if not client.get("call_end_received"):
            issues.append(
                {
                    "side": "participant_client",
                    "call_session_id": session_id,
                    "issue": "socket closed before call_end",
                    "code": client.get("code"),
                    "reason": client.get("reason", ""),
                }
            )
        expected_code = int(client.get("expected_close_code", 1000))
        if expected_code not in ALLOWED_CALL_CLOSE_CODES:
            issues.append(
                {
                    "side": "participant_client",
                    "call_session_id": session_id,
                    "issue": "invalid expected close code",
                    "code": expected_code,
                }
            )
        for side, _event, code, reason in (
            ("participant_client", client, client.get("code"), client.get("reason", "")),
            (
                "participant_core",
                core,
                core.get("socket_close_code"),
                core.get("socket_close_reason", ""),
            ),
        ):
            if code != expected_code:
                issues.append(
                    {
                        "side": side,
                        "call_session_id": session_id,
                        "issue": "unexpected close code",
                        "code": code,
                        "expected_code": expected_code,
                    }
                )
            if reason:
                issues.append(
                    {
                        "side": side,
                        "call_session_id": session_id,
                        "issue": "nonempty close reason",
                        "code": code,
                        "reason": reason,
                    }
                )
        if core.get("socket_close_initiator") != "server":
            issues.append(
                {
                    "side": "participant_core",
                    "call_session_id": session_id,
                    "issue": "socket was not closed by the call server",
                    "initiator": core.get("socket_close_initiator"),
                }
            )
        if not core.get("call_end_sent"):
            issues.append(
                {
                    "side": "participant_core",
                    "call_session_id": session_id,
                    "issue": "server did not send call_end",
                }
            )
        if client.get("call_end_reason") != core.get("reason"):
            issues.append(
                {
                    "side": "participant_core",
                    "call_session_id": session_id,
                    "issue": "call lifecycle reason mismatch",
                    "client_reason": client.get("call_end_reason"),
                    "core_reason": core.get("reason"),
                }
            )
        if client.get("investigation_id") != core.get("investigation_id") or client.get(
            "participant_id"
        ) != core.get("participant_id"):
            issues.append(
                {
                    "side": "participant_core",
                    "call_session_id": session_id,
                    "issue": "call identity mismatch",
                }
            )
    return issues


def _provider_close_issues(
    server_closes: list[dict[str, Any]],
    core_closes: list[dict[str, Any]],
    *,
    observe_server: bool,
) -> list[dict[str, Any]]:
    """Check provider close codes and reasons, matching local emulator events when available."""
    issues: list[dict[str, Any]] = []
    sides = [("core_provider_client", core_closes)]
    if observe_server:
        sides.append(("provider_server", server_closes))
    by_side: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for side, events in sides:
        by_id: dict[str, list[dict[str, Any]]] = {}
        by_side[side] = by_id
        for event in events:
            session_id = str(event.get("session_id") or "")
            if not session_id:
                issues.append({"side": side, "issue": "missing provider session ID", **event})
                continue
            by_id.setdefault(session_id, []).append(event)
            code, reason = event.get("code"), event.get("reason", "")
            if code not in ALLOWED_PROVIDER_CLOSE_CODES:
                issues.append(
                    {
                        "session_id": session_id,
                        "side": side,
                        "issue": "unexpected close code",
                        "code": code,
                        "reason": reason,
                    }
                )
            if reason:
                issues.append(
                    {
                        "session_id": session_id,
                        "side": side,
                        "issue": "nonempty close reason",
                        "code": code,
                        "reason": reason,
                    }
                )
        for session_id, matches in by_id.items():
            if len(matches) > 1:
                issues.append(
                    {
                        "session_id": session_id,
                        "side": side,
                        "issue": "duplicate close event",
                    }
                )

    if observe_server:
        server_by_id = by_side.get("provider_server", {})
        core_by_id = by_side.get("core_provider_client", {})
        for session_id in sorted(set(server_by_id) | set(core_by_id)):
            server_matches = server_by_id.get(session_id, [])
            core_matches = core_by_id.get(session_id, [])
            if len(server_matches) != 1 or len(core_matches) != 1:
                side = "provider_server" if not server_matches else "core_provider_client"
                issues.append(
                    {
                        "session_id": session_id,
                        "side": side,
                        "issue": "provider close is missing on one side",
                    }
                )
                continue
            server, core = server_matches[0], core_matches[0]
            if (server.get("code"), server.get("reason", "")) != (
                core.get("code"),
                core.get("reason", ""),
            ):
                issues.append(
                    {
                        "session_id": session_id,
                        "side": "provider_server",
                        "issue": "provider close differs between sides",
                        "server_code": server.get("code"),
                        "server_reason": server.get("reason", ""),
                        "core_code": core.get("code"),
                        "core_reason": core.get("reason", ""),
                    }
                )
    return issues


def _socket_event_key(event: dict[str, Any]) -> str:
    return str(event.get("socket_id") or event.get("call_session_id") or "")


def _first_three_call_at(events: list[dict[str, Any]]) -> float | None:
    active: set[str] = set()
    ordered = sorted(
        events,
        key=lambda item: (
            float(item.get("at_monotonic", 0)),
            0 if item.get("event") == "close" else 1,
        ),
    )
    for event in ordered:
        socket_id = _socket_event_key(event)
        if not socket_id:
            continue
        if event.get("event") == "open":
            active.add(socket_id)
            if len(active) >= 3:
                return float(event["at_monotonic"])
        elif event.get("event") == "close":
            active.discard(socket_id)
    return None


def _active_socket_ids(events: list[dict[str, Any]], *, at_or_before: float) -> set[str]:
    active: set[str] = set()
    ordered = sorted(
        events,
        key=lambda item: (
            float(item.get("at_monotonic", 0)),
            0 if item.get("event") == "close" else 1,
        ),
    )
    for event in ordered:
        if float(event.get("at_monotonic", 0)) > at_or_before:
            break
        socket_id = _socket_event_key(event)
        if not socket_id:
            continue
        if event.get("event") == "open":
            active.add(socket_id)
        elif event.get("event") == "close":
            active.discard(socket_id)
    return active


def _peak_socket_count(events: list[dict[str, Any]], *, started_at: float, ended_at: float) -> int:
    active = _active_socket_ids(events, at_or_before=started_at)
    peak = len(active)
    ordered = sorted(
        (event for event in events if started_at < float(event.get("at_monotonic", 0)) <= ended_at),
        key=lambda item: (
            float(item.get("at_monotonic", 0)),
            0 if item.get("event") == "close" else 1,
        ),
    )
    for event in ordered:
        socket_id = _socket_event_key(event)
        if not socket_id:
            continue
        if event.get("event") == "open":
            active.add(socket_id)
        elif event.get("event") == "close":
            active.discard(socket_id)
        peak = max(peak, len(active))
    return peak


def _three_call_window(
    events: list[dict[str, Any]], *, started_at: float, ended_at: float
) -> dict[str, Any]:
    if ended_at < started_at:
        raise ValueError("call coverage window ends before it starts")
    ordered = sorted(
        events,
        key=lambda item: (
            float(item.get("at_monotonic", 0)),
            0 if item.get("event") == "close" else 1,
        ),
    )
    active: set[str] = set()
    relevant: list[tuple[float, str, str]] = []
    for event in ordered:
        at = float(event.get("at_monotonic", 0))
        socket_id = _socket_event_key(event)
        kind = str(event.get("event", ""))
        if not socket_id or kind not in {"open", "close"}:
            continue
        if at <= started_at:
            if kind == "open":
                active.add(socket_id)
            else:
                active.discard(socket_id)
        elif at < ended_at:
            relevant.append((at, kind, socket_id))

    three = 0.0
    under = 0.0
    cursor = started_at
    gaps: list[dict[str, float]] = []

    def add_interval(end: float) -> None:
        nonlocal cursor, three, under
        duration = max(0.0, end - cursor)
        if len(active) >= 3:
            three += duration
        else:
            under += duration
            if duration > 0:
                if gaps and math.isclose(gaps[-1]["end"], cursor, abs_tol=0.000001):
                    gaps[-1]["end"] = end
                    gaps[-1]["duration_seconds"] = gaps[-1]["end"] - gaps[-1]["start"]
                else:
                    gaps.append({"start": cursor, "end": end, "duration_seconds": duration})
        cursor = end

    for at, kind, socket_id in relevant:
        add_interval(at)
        if kind == "open":
            active.add(socket_id)
        else:
            active.discard(socket_id)
    add_interval(ended_at)
    for gap in gaps:
        gap["start"] = round(gap["start"], 3)
        gap["end"] = round(gap["end"], 3)
        gap["duration_seconds"] = round(gap["duration_seconds"], 3)
        gap["reason"] = "fewer than three participant call sockets were open during a handoff"
    duration = ended_at - started_at
    return {
        "window_seconds": round(duration, 3),
        "three_call_seconds": round(three, 3),
        "under_three_call_seconds": round(under, 3),
        "coverage_ratio": round(three / duration, 6) if duration else 1.0,
        "max_handoff_gap_seconds": round(
            max((float(gap["duration_seconds"]) for gap in gaps), default=0.0), 3
        ),
        "handoff_gaps": gaps,
    }


def _read_socket_events(event_paths: list[Path]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in event_paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


async def _json_get(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    response = await client.get(url)
    response.raise_for_status()
    return response.json()


async def _probe_stream_cap(core_url: str, automation_key: str) -> dict[str, Any]:
    headers = {"X-Automation-Key": automation_key}
    url = core_url.replace("http://", "ws://", 1) + "/v1/voice/stream"
    options = {"additional_headers": headers, "ping_interval": None, "open_timeout": 10}
    sockets: list[websockets.ClientConnection] = []
    client_close_events: list[dict[str, Any]] = []
    refused = False
    usage_at_limit: dict[str, Any] = {}
    third_messages: list[dict[str, Any]] = []

    async def start_stream() -> websockets.ClientConnection:
        ws = await websockets.connect(url, **options)
        await ws.send(json.dumps({"type": "start", "language_code": ["hi-IN"]}))
        first = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if first.get("type") != "ready":
            await ws.close()
            raise RuntimeError(f"cap probe stream failed to start: {first}")
        return ws

    async def finish_stream(ws: websockets.ClientConnection) -> None:
        try:
            await ws.send(json.dumps({"type": "stop"}))
            async with asyncio.timeout(10):
                while True:
                    message = await ws.recv()
                    if isinstance(message, str) and json.loads(message).get("type") == "closed":
                        break
        finally:
            await ws.close()
            client_close_events.append({"code": ws.close_code, "reason": ws.close_reason or ""})

    try:
        sockets.append(await start_stream())
        sockets.append(await start_stream())
        async with httpx.AsyncClient(base_url=core_url, headers=headers, timeout=10) as client:
            usage_at_limit = await _json_get(client, "/v1/voice/usage")
            refused_ws = await websockets.connect(url, **options)
            await refused_ws.send(json.dumps({"type": "start", "language_code": ["hi-IN"]}))
            async with asyncio.timeout(10):
                while True:
                    raw = await refused_ws.recv()
                    if not isinstance(raw, str):
                        continue
                    message = json.loads(raw)
                    third_messages.append(message)
                    if message.get("type") == "error" and "VOICE_TOO_MANY_STREAMS" in str(
                        message.get("message", "")
                    ):
                        refused = True
                    if message.get("type") == "closed":
                        break
            await refused_ws.close()
            client_close_events.append(
                {"code": refused_ws.close_code, "reason": refused_ws.close_reason or ""}
            )
    finally:
        await asyncio.gather(*(finish_stream(ws) for ws in sockets), return_exceptions=False)

    return {
        "configured_stream_cap": CAP_PROBE_STREAM_LIMIT,
        "requested_simultaneous_streams": 3,
        "refused_at_cap": refused,
        "open_streams_when_full": usage_at_limit.get("open_streams"),
        "peak_streams_when_full": usage_at_limit.get("peak_streams"),
        "max_streams": (usage_at_limit.get("limits") or {}).get("max_streams"),
        "third_stream_messages": third_messages,
        "client_socket_closes": client_close_events,
    }


async def _tts_rest_probe(core_url: str, automation_key: str) -> dict[str, Any]:
    async with httpx.AsyncClient(
        base_url=core_url, headers={"X-Automation-Key": automation_key}, timeout=30
    ) as client:
        response = await client.post(
            "/v1/voice/tts",
            json={"text": "load test audio probe", "language": "en-IN"},
        )
    response.raise_for_status()
    if not response.content.startswith(b"RIFF"):
        raise RuntimeError("TTS REST probe did not return WAV data")
    return {"status": response.status_code, "wav_bytes": len(response.content)}


async def _sample_runtime(
    *,
    core: ManagedProcess,
    sim: ManagedProcess,
    core_url: str,
    fake_url: str | None,
    automation_key: str,
    started: float,
    stop: asyncio.Event,
    samples: list[dict[str, Any]],
    sample_errors: list[str],
) -> None:
    next_sample = time.monotonic()
    while True:
        now = time.monotonic()
        core_info = _process_snapshot(core.pid)
        sim_info = _process_snapshot(sim.pid)
        sample: dict[str, Any] = {
            "elapsed_seconds": round(now - started, 3),
            "core_rss_bytes": core_info["rss_bytes"],
            "core_process_handles": core_info["handles"],
            "sim_rss_bytes": sim_info["rss_bytes"],
            "sim_process_handles": sim_info["handles"],
        }
        try:
            async with httpx.AsyncClient(
                base_url=core_url,
                headers={"X-Automation-Key": automation_key},
                timeout=4,
            ) as core_client:
                usage = await _json_get(core_client, "/v1/voice/usage")
            sample["open_streams"] = usage.get("open_streams")
            sample["peak_streams"] = usage.get("peak_streams")
            sample["stream_cap"] = (usage.get("limits") or {}).get("max_streams")
        except (httpx.HTTPError, ValueError) as exc:
            sample_errors.append(f"voice usage sample: {type(exc).__name__}")
        if fake_url is not None:
            try:
                async with httpx.AsyncClient(base_url=fake_url, timeout=4) as fake_client:
                    fake_metrics = await _json_get(fake_client, "/metrics")
                sample["provider_open_streams"] = fake_metrics.get("active_websocket_sessions")
                sample["provider_peak_streams"] = fake_metrics.get("peak_active_websocket_sessions")
            except (httpx.HTTPError, ValueError) as exc:
                sample_errors.append(f"provider metrics sample: {type(exc).__name__}")
        samples.append(sample)
        if stop.is_set():
            return
        next_sample += RSS_SAMPLE_INTERVAL_S
        await asyncio.sleep(max(0.0, next_sample - time.monotonic()))


def _bot_command(
    *,
    options: LoadOptions,
    core_url: str,
    sim_url: str,
    automation_key: str,
    parallel: int,
    silent_first: bool,
    delay_first_answer_s: float,
    barge_in_first: bool,
    keep_calls_open: bool,
    idle_probe: bool,
) -> tuple[list[str], dict[str, str]]:
    args = [
        sys.executable,
        str(ROOT / "scripts" / "voice_bot_run.py"),
        "--core",
        core_url,
        "--sim",
        sim_url,
        "--parallel",
        str(parallel),
        "--timeout",
        "180",
        "--play",
    ]
    if keep_calls_open:
        args.append("--keep-calls-open")
    if idle_probe:
        args.append("--idle-probe")
    if options.live:
        assert options.clips is not None
        args.extend(["--clips", str(options.clips)])
    else:
        args.append("--synthetic")
    if silent_first:
        args.append("--silent-first")
    if delay_first_answer_s > 0:
        args.extend(["--delay-first-answer", str(delay_first_answer_s)])
    if barge_in_first:
        args.append("--barge-in-first")
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["CORE_AUTOMATION_KEY"] = automation_key
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "scripts"), env.get("PYTHONPATH", "")]).rstrip(
        os.pathsep
    )
    return args, env


def _parse_bot_result(output: str, returncode: int) -> dict[str, Any]:
    if returncode != 0:
        tail = "\n".join(output.splitlines()[-80:])
        raise RuntimeError(f"voice bot run failed with exit code {returncode}:\n{tail}")
    summary_line = next(
        (
            line.removeprefix("LOAD_RESULT_JSON=")
            for line in reversed(output.splitlines())
            if line.startswith("LOAD_RESULT_JSON=")
        ),
        None,
    )
    if summary_line is None:
        raise RuntimeError("voice bot run did not emit its load result")
    return json.loads(summary_line)


def _run_bot(
    *,
    options: LoadOptions,
    run_dir: Path,
    core_url: str,
    sim_url: str,
    automation_key: str,
    parallel: int,
    silent_first: bool,
    delay_first_answer_s: float,
    barge_in_first: bool,
    keep_calls_open: bool,
    idle_probe: bool,
    bot_log: Path,
    socket_event_log: Path | None = None,
) -> dict[str, Any]:
    args, env = _bot_command(
        options=options,
        core_url=core_url,
        sim_url=sim_url,
        automation_key=automation_key,
        parallel=parallel,
        silent_first=silent_first,
        delay_first_answer_s=delay_first_answer_s,
        barge_in_first=barge_in_first,
        keep_calls_open=keep_calls_open,
        idle_probe=idle_probe,
    )
    if socket_event_log is not None:
        args.extend(["--socket-events", str(socket_event_log)])
    result = subprocess.run(
        args,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=240,
        check=False,
    )
    with bot_log.open("a", encoding="utf-8") as file:
        file.write(f"\n--- investigation {datetime.now(UTC).isoformat()} ---\n")
        file.write(result.stdout)
        file.write(result.stderr)
    return _parse_bot_result(result.stdout + result.stderr, result.returncode)


def _percentile_fields(investigations: list[dict[str, Any]]) -> dict[str, Any]:
    turn_latencies = [
        float(value)
        for investigation in investigations
        for value in investigation.get("emulated_eos_to_answer_ms", [])
    ]
    return {
        "label": "Emulated provider only. Synthetic audio end to answer frame, milliseconds.",
        "sample_count": len(turn_latencies),
        "p50_ms": _percentile(turn_latencies, 0.5),
        "p95_ms": _percentile(turn_latencies, 0.95),
        "min_ms": round(min(turn_latencies), 3) if turn_latencies else None,
        "max_ms": round(max(turn_latencies), 3) if turn_latencies else None,
    }


def _notes(summary: dict[str, Any]) -> str:
    memory = summary["memory"]
    cap = summary["stream_cap_probe"]
    paths = summary["coverage"]
    closes = summary["websocket_closes"]
    provider = summary["provider"]
    latency = summary["latency"]
    lines = [
        "# Emulated voice load report",
        "",
        f"Generated: {summary['generated_at_utc']}",
        f"Load window: {summary['load_duration_seconds']:.1f} seconds; "
        f"target {summary['target_duration_seconds']:.1f} seconds.",
        f"Completed S1 investigations: {summary['investigation_count']}.",
        f"Time with at least three participant call sockets open: "
        f"{summary['three_call_seconds']:.1f} seconds.",
        f"Time below three open call sockets during handoffs: "
        f"{summary['three_call_window']['under_three_call_seconds']:.3f} seconds "
        f"({summary['three_call_window']['coverage_ratio']:.2%} three-call coverage).",
        f"Longest measured handoff gap: "
        f"{summary['three_call_window']['max_handoff_gap_seconds']:.3f} seconds.",
        f"Participant call socket peak during the measured window: "
        f"{summary['peak_participant_call_sockets']}.",
        "",
        "## Results",
        "",
        "- Investigation status verified, truth correct, commitment verified, and replay "
        f"byte-identical: {summary['all_investigations_passed']}.",
        f"- Participant call socket peak: {summary['peak_participant_call_sockets']}.",
        f"- Participant call socket closes: {closes['participant_client_count']} "
        f"client-side and {closes['participant_core_count']} core-side.",
        f"- Emulated Prisma WebSocket closes: {closes['provider_server_count']} "
        f"provider-side and {closes['provider_core_count']} core-side.",
        f"- Unexpected WebSocket closes: {closes['unexpected_count']}.",
        f"- Barge-ins: {paths['barge_ins']}; silence re-prompts: "
        f"{paths['silence_reprompts']}; silent releases: {paths['silent_releases']}; "
        f"idle call heartbeats: {paths['idle_heartbeats']}; "
        f"withdrawn questions: {paths['withdrawn_questions']}.",
        f"- Governor cap sub-run: configured {cap['configured_stream_cap']}, "
        f"requested {cap['requested_simultaneous_streams']}, "
        f"refused over-cap request {cap['refused_at_cap']}, "
        f"peak at limit {cap['peak_streams_when_full']}.",
        f"- Fake provider requests: STT REST {provider['stt_rest_requests']}, "
        f"STT WebSocket {provider['websocket_sessions_opened']}, "
        f"TTS REST {provider['tts_rest_requests']}, TTS SSE {provider['tts_sse_requests']}.",
        f"- Emulated turn latency p50 {latency['p50_ms']} ms, "
        f"p95 {latency['p95_ms']} ms from {latency['sample_count']} turns.",
        "",
        "## Memory and handles",
        "",
        f"RSS was sampled every {RSS_SAMPLE_INTERVAL_S:.0f} seconds. Core: "
        f"{memory['core']['samples']} samples, slope "
        f"{memory['core']['slope_mib_per_min']} MiB/min, change "
        f"{memory['core']['growth_mib']} MiB.",
        f"Simulator: {memory['sim']['samples']} samples, slope "
        f"{memory['sim']['slope_mib_per_min']} MiB/min, change "
        f"{memory['sim']['growth_mib']} MiB.",
        f"Leak limits for the ten-minute run: slope at most "
        f"{RSS_SLOPE_LIMIT_MIB_PER_MIN:.1f} MiB/min and start-to-end growth at most "
        f"{RSS_GROWTH_LIMIT_MIB:.0f} MiB per process. The slope permits up to 10 MiB "
        "of growth over ten minutes; the separate limit absorbs working-set noise.",
        f"Peak observed process handles: core {memory['core_peak_handles']}, "
        f"simulator {memory['sim_peak_handles']}. Asyncio task counts were not sampled.",
        "",
        "## Coverage and limits",
        "",
        "- Simulator, core, fake Gnani, and voice bots ran as separate processes against "
        "the task's PostgreSQL database.",
        "- The ten-minute window starts at the first point with three open participant calls. "
        "Up to three complete S1 bot runs may overlap during handoffs, with at most nine call "
        "sockets open. The third run starts when five or fewer calls remain open. "
        "Measured handoff gaps are limited to two seconds each and at most one percent of the "
        "full window.",
        "- Fake Prisma decoded a test-only text marker carried in synthetic PCM. The marker "
        "is not audible speech and is never sent to live Gnani.",
        "- Fake Timbre returned deterministic PCM over REST and paced SSE chunks. The "
        "timings describe the local emulator only.",
        "- The run covered decision, approval, repair, verification, reveal, event-log "
        "replay, call heartbeats, barge-in, silence re-prompt and release, question "
        "withdrawal, and stream-cap refusal.",
        "- No live Gnani run was performed. This report does not measure real speech "
        "recognition, real TTS, provider latency, or live account capacity.",
        "- Process handles were sampled. Asyncio task counts, file descriptor types, "
        "network packet loss, and live Gnani behavior were not measured.",
        "",
    ]
    return "\n".join(lines)


def _write_report(report_dir: Path, summary: dict[str, Any]) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (report_dir / "NOTES.md").write_text(_notes(summary), encoding="utf-8")


def _write_private_live_evidence(scratch_root: Path, summary: dict[str, Any]) -> Path:
    evidence_dir = scratch_root / "live-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_dir / f"live-{uuid.uuid4().hex}.json"
    evidence = json.loads(json.dumps(summary))
    evidence["latency"] = None
    for investigation in evidence.get("investigations", []):
        investigation.pop("emulated_eos_to_transcript_ms", None)
        investigation.pop("emulated_eos_to_answer_ms", None)
    evidence["private_evidence_path"] = str(evidence_path)
    evidence_path.write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return evidence_path


async def run_load(options: LoadOptions) -> dict[str, Any]:
    _validate_options(options)
    if options.live and not options.test_local_provider and not _load_key_configured():
        raise RuntimeError("live mode requires GNANI_API_KEY in the environment or worktree .env")
    uses_fake_provider = not options.live or options.test_local_provider
    ports = [options.core_port, options.sim_port]
    if uses_fake_provider:
        ports.append(options.fake_port)
    occupied = [port for port in ports if not _port_is_free(port)]
    if occupied:
        raise RuntimeError(f"load ports are already in use: {occupied}")

    run_dir = options.scratch_root / f"load-{uuid.uuid4().hex[:10]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    logs = run_dir / "logs"
    logs.mkdir()
    generated_at = datetime.now(UTC).isoformat()
    signing_key = generate_private_key_b64()
    operator_key = secrets.token_urlsafe(24)
    oracle_key = secrets.token_urlsafe(24)
    automation_key = secrets.token_urlsafe(24)
    public_key = public_key_b64(private_key_from_b64(signing_key))
    core_url = f"http://127.0.0.1:{options.core_port}"
    sim_url = f"http://127.0.0.1:{options.sim_port}"
    fake_url = f"http://127.0.0.1:{options.fake_port}" if uses_fake_provider else None
    fake_event_log = run_dir / "provider-events.jsonl"

    base_env = os.environ.copy()
    base_env["PYTHONIOENCODING"] = "utf-8"
    base_env["PYTHONUNBUFFERED"] = "1"

    processes: list[ManagedProcess] = []
    sim_env, core_env = _environment(
        options=options,
        run_dir=run_dir,
        signing_key=signing_key,
        operator_key=operator_key,
        oracle_key=oracle_key,
        automation_key=automation_key,
        public_key=public_key,
        fake_url=fake_url,
        stream_cap=CAP_PROBE_STREAM_LIMIT,
    )
    fake_process: ManagedProcess | None = None
    if uses_fake_provider:
        fake_process = ManagedProcess(
            "fake-gnani",
            [
                sys.executable,
                str(FAKE_SERVER),
                "--port",
                str(options.fake_port),
                "--event-log",
                str(fake_event_log),
            ],
            sim_env,
            logs / "fake-gnani.log",
        )
        processes.append(fake_process)
    sim_process = ManagedProcess(
        "sim", [sys.executable, "-m", "pramana_sim"], sim_env, logs / "sim.log"
    )
    core_process = ManagedProcess(
        "core", [sys.executable, "-m", "pramana_core"], core_env, logs / "core.log"
    )
    processes.extend([sim_process, core_process])
    samples: list[dict[str, Any]] = []
    sample_errors: list[str] = []
    investigations: list[dict[str, Any]] = []
    cap_probe: dict[str, Any] | None = None
    tts_probe: dict[str, Any] | None = None
    provider_final: dict[str, Any] = {}
    usage_final: dict[str, Any] = {}
    sample_task: asyncio.Task[None] | None = None
    sample_stop = asyncio.Event()
    window_started: float | None = None
    window_ended: float | None = None
    event_paths: list[Path] = []
    jobs: dict[int, BotProcess] = {}
    next_bot_index = 0
    failure: BaseException | None = None
    bot_log = logs / "voice-bots.log"

    async def launch_parallel_bot(index: int) -> None:
        event_path = logs / f"bot-{index:04d}.sockets.jsonl"
        log_path = logs / f"bot-{index:04d}.log"
        args, env = _bot_command(
            options=options,
            core_url=core_url,
            sim_url=sim_url,
            automation_key=automation_key,
            parallel=3,
            silent_first=False,
            delay_first_answer_s=2.0 if index % 2 else 0.0,
            barge_in_first=index == 1,
            keep_calls_open=True,
            idle_probe=False,
        )
        args.extend(["--socket-events", str(event_path)])
        job = BotProcess(f"investigation run {index + 1}", log_path, bot_log)
        await job.start(args, env)
        jobs[index] = job
        event_paths.append(event_path)

    try:
        await asyncio.to_thread(_ensure_postgres_and_database, options.database_url, base_env)
        if fake_process is not None:
            fake_process.start()
            _wait_http(fake_process, f"{fake_url}/health")
        sim_process.start()
        _wait_http(sim_process, f"{sim_url}/health")
        core_process.start()
        _wait_http(core_process, f"{core_url}/ready")

        cap_probe = await _probe_stream_cap(core_url, automation_key)
        core_process.stop()
        core_env["GNANI_MAX_STREAMS"] = str(options.stream_cap)
        core_process.start()
        _wait_http(core_process, f"{core_url}/ready")

        tts_probe = await _tts_rest_probe(core_url, automation_key)
        preflight_events = logs / "preflight.sockets.jsonl"
        preflight = await asyncio.to_thread(
            _run_bot,
            options=options,
            run_dir=run_dir,
            core_url=core_url,
            sim_url=sim_url,
            automation_key=automation_key,
            parallel=1,
            silent_first=True,
            delay_first_answer_s=0,
            barge_in_first=False,
            keep_calls_open=False,
            idle_probe=True,
            bot_log=bot_log,
            socket_event_log=preflight_events,
        )
        investigations.append(preflight)
        event_paths.append(preflight_events)

        await launch_parallel_bot(next_bot_index)
        next_bot_index += 1
        while True:
            now = time.monotonic()
            socket_events = _read_socket_events(event_paths)
            if window_started is None:
                first_three = _first_three_call_at(socket_events)
                if first_three is not None:
                    window_started = first_three
                    window_ended = window_started + options.duration_s
                    sample_task = asyncio.create_task(
                        _sample_runtime(
                            core=core_process,
                            sim=sim_process,
                            core_url=core_url,
                            fake_url=fake_url,
                            automation_key=automation_key,
                            started=window_started,
                            stop=sample_stop,
                            samples=samples,
                            sample_errors=sample_errors,
                        )
                    )

            completed = [index for index, job in jobs.items() if job.returncode is not None]
            for index in completed:
                investigations.append(await jobs.pop(index).result())

            if window_ended is not None and now >= window_ended:
                if not jobs:
                    break
            elif window_started is None:
                if not jobs:
                    await launch_parallel_bot(next_bot_index)
                    next_bot_index += 1
            elif _should_launch_handoff_run(
                running_jobs=len(jobs),
                active_call_sockets=len(_active_socket_ids(socket_events, at_or_before=now)),
            ):
                await launch_parallel_bot(next_bot_index)
                next_bot_index += 1

            if window_started is not None and window_ended is not None and now < window_ended:
                for job in jobs.values():
                    if job.started_at is not None and now - job.started_at > 240:
                        raise RuntimeError(f"{job.name} exceeded the 240 second process limit")
            await asyncio.sleep(0.1)

        sample_stop.set()
        if sample_task is not None:
            await sample_task
            sample_task = None

        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            headers = {"X-Automation-Key": automation_key}
            async with httpx.AsyncClient(
                base_url=core_url, headers=headers, timeout=5
            ) as core_client:
                usage_final = await _json_get(core_client, "/v1/voice/usage")
            if fake_url is not None:
                async with httpx.AsyncClient(base_url=fake_url, timeout=5) as provider_client:
                    provider_final = await _json_get(provider_client, "/metrics")
                provider_closed = provider_final.get("active_websocket_sessions") == 0
            else:
                provider_closed = True
            if provider_closed and usage_final.get("open_streams") == 0:
                break
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError("provider streams remained open after the call bots finished")
        await asyncio.sleep(1.0)
    except BaseException as exc:
        failure = exc
        sample_stop.set()
        for job in jobs.values():
            await job.stop()
        if sample_task is not None:
            sample_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sample_task
            sample_task = None
    finally:
        for process in reversed(processes):
            process.stop()

    socket_events = _read_socket_events(event_paths)
    if window_started is None:
        window_started = time.monotonic()
        window_ended = window_started
    assert window_ended is not None
    three_call_window = _three_call_window(
        socket_events, started_at=window_started, ended_at=window_ended
    )
    load_duration_s = three_call_window["window_seconds"]
    core_call_closes = _structured_events(logs / "core.log", "call_ended")
    core_provider_closes = _structured_events(logs / "core.log", "gnani_ws_closed")
    participant_closes = [
        close
        for investigation in investigations
        for close in investigation.get("call_socket_closes", [])
    ]
    provider_server_closes = list(provider_final.get("websocket_close_events", []))
    unexpected_closes = _call_close_issues(participant_closes, core_call_closes)
    unexpected_closes.extend(
        _provider_close_issues(
            provider_server_closes,
            core_provider_closes,
            observe_server=fake_url is not None,
        )
    )
    cap_probe_closes = (cap_probe or {}).get("client_socket_closes", [])
    for close in cap_probe_closes:
        if close.get("code") != 1000:
            unexpected_closes.append(
                {"side": "stream_cap_probe", "issue": "unexpected close code", **close}
            )
        if close.get("reason"):
            unexpected_closes.append(
                {"side": "stream_cap_probe", "issue": "nonempty close reason", **close}
            )

    core_rss = _rss_summary(samples, "core_rss_bytes")
    sim_rss = _rss_summary(samples, "sim_rss_bytes")
    core_handles = [
        int(sample["core_process_handles"])
        for sample in samples
        if sample.get("core_process_handles") is not None
    ]
    sim_handles = [
        int(sample["sim_process_handles"])
        for sample in samples
        if sample.get("sim_process_handles") is not None
    ]
    core_usage_samples = [
        int(sample["peak_streams"]) for sample in samples if sample.get("peak_streams") is not None
    ]
    provider_usage_samples = [
        int(sample["provider_peak_streams"])
        for sample in samples
        if sample.get("provider_peak_streams") is not None
    ]
    full_run = options.duration_s >= 600
    memory_checks: list[dict[str, Any]] = []
    if full_run:
        for service_name, service_rss in (("core", core_rss), ("simulator", sim_rss)):
            slope = service_rss["slope_mib_per_min"]
            growth = service_rss["growth_mib"]
            if slope is None or growth is None:
                memory_checks.append({"service": service_name, "passed": False})
            else:
                passed = (
                    float(slope) <= RSS_SLOPE_LIMIT_MIB_PER_MIN
                    and float(growth) <= RSS_GROWTH_LIMIT_MIB
                )
                memory_checks.append(
                    {
                        "service": service_name,
                        "passed": passed,
                        "slope_mib_per_min": slope,
                        "growth_mib": growth,
                    }
                )

    peak_calls = _peak_socket_count(socket_events, started_at=window_started, ended_at=window_ended)
    three_call_seconds = float(three_call_window["three_call_seconds"])
    paths = {
        "barge_ins": sum(int(item.get("barge_ins", 0)) for item in investigations),
        "silence_reprompts": sum(int(item.get("silence_reprompts", 0)) for item in investigations),
        "silent_releases": sum(
            bool(item.get("silent_participant_released", False)) for item in investigations
        ),
        "idle_heartbeats": sum(int(item.get("idle_heartbeats", 0)) for item in investigations),
        "withdrawn_questions": sum(
            int(item.get("withdrawn_questions", 0)) for item in investigations
        ),
    }
    all_passed = bool(investigations) and all(
        item.get("status") == "verified"
        and item.get("revealed_correct") is True
        and item.get("commitment_verified") is True
        and item.get("replay_identical") is True
        and item.get("replay_replayed_sha256") == item.get("replay_recorded_sha256")
        for item in investigations
    )
    provider_counts = {
        key: provider_final.get(key, 0)
        for key in (
            "stt_rest_requests",
            "tts_rest_requests",
            "tts_sse_requests",
            "synthetic_transcripts_decoded",
            "websocket_sessions_opened",
            "websocket_sessions_closed",
            "peak_active_websocket_sessions",
        )
    }
    all_failures: list[str] = []
    if failure is not None:
        process_text = "\n".join(
            f"{process.name} log:\n{process.tail(40)}" for process in processes
        )
        all_failures.append(f"runtime error: {type(failure).__name__}: {failure}\n{process_text}")
    if not isinstance(cap_probe, dict) or not cap_probe.get("refused_at_cap"):
        all_failures.append("lower stream-cap sub-run did not refuse the over-cap request")
    if cap_probe and (
        cap_probe.get("open_streams_when_full") != CAP_PROBE_STREAM_LIMIT
        or cap_probe.get("peak_streams_when_full") != CAP_PROBE_STREAM_LIMIT
        or cap_probe.get("max_streams") != CAP_PROBE_STREAM_LIMIT
    ):
        all_failures.append("lower stream-cap sub-run did not hold exactly the configured limit")
    if fake_url is not None:
        if provider_final.get("websocket_sessions_opened") != provider_final.get(
            "websocket_sessions_closed"
        ):
            all_failures.append("fake provider WebSocket sessions did not all close")
        if len(core_provider_closes) != int(provider_final.get("websocket_sessions_closed", 0)):
            all_failures.append("core and fake provider WebSocket close counts differ")
        if provider_final.get("tts_rest_requests", 0) < 1:
            all_failures.append("fake provider did not receive a TTS REST request")
        if provider_final.get("tts_sse_requests", 0) < 1:
            all_failures.append("fake provider did not receive a TTS SSE request")
    if tts_probe is None or tts_probe.get("status") != 200:
        all_failures.append("TTS REST probe did not pass")
    governor_peak = max(
        [int(usage_final.get("peak_streams", 0))] + [int(value) for value in core_usage_samples]
    )
    stream_cap_respected = governor_peak <= options.stream_cap
    if not stream_cap_respected:
        all_failures.append("governor peak exceeded its configured stream cap")
    if fake_url is not None and int(provider_final.get("peak_active_websocket_sessions", 0)) > (
        options.stream_cap
    ):
        all_failures.append("fake provider observed more streams than the governor cap")
    if usage_final.get("open_streams") != 0:
        all_failures.append("governor still had open streams after the bots finished")
    if not investigations:
        all_failures.append("no S1 investigations completed")
    if not all_passed:
        all_failures.append(
            "an investigation was not correct, verified, commitment-checked, and replay-identical"
        )
    if peak_calls < 3:
        all_failures.append("three participant call sockets were never open at once")
    if peak_calls > MAX_PARALLEL_CALL_SOCKETS:
        all_failures.append("participant call sockets exceeded the handoff limit")
    allowed_gap_seconds = max(2.0, options.duration_s * MAX_CALL_HANDOFF_GAP_RATIO)
    if three_call_window["under_three_call_seconds"] > allowed_gap_seconds:
        all_failures.append("total call handoff gaps exceeded the allowed duration")
    if three_call_window["max_handoff_gap_seconds"] > MAX_CALL_HANDOFF_GAP_S:
        all_failures.append("a single call handoff gap exceeded the allowed duration")
    first_result = investigations[0] if investigations else {}
    if not first_result.get("silent_participant_released"):
        all_failures.append("silent participant was not released after re-prompt")
    if int(first_result.get("silence_reprompts", 0)) < 1:
        all_failures.append("silent participant did not receive a re-prompt")
    if int(first_result.get("idle_heartbeats", 0)) < 1:
        all_failures.append("no idle call heartbeat was observed")
    if paths["barge_ins"] < 1:
        all_failures.append("no barge-in was observed")
    if paths["withdrawn_questions"] < 1:
        all_failures.append("no question withdrawal was observed")
    if unexpected_closes:
        all_failures.append("unexpected WebSocket close lifecycle, code, or reason was observed")
    if sample_errors:
        all_failures.append(f"runtime metric sampling errors: {sample_errors[:5]}")
    expected_provider_sessions = (
        sum(int(item.get("stt_streams_opened", 0)) for item in investigations) + 2
    )
    if len(core_provider_closes) != expected_provider_sessions:
        all_failures.append(
            "provider close events do not match successful STT sessions and the two cap probes"
        )
    if full_run and not all(item.get("passed") for item in memory_checks):
        all_failures.append("RSS growth exceeded the configured leak thresholds")

    keep_failure_artifacts = bool(
        all_failures and os.environ.get("PRAMANA_LOAD_KEEP_FAILURE_ARTIFACTS") == "1"
    )
    if keep_failure_artifacts:
        all_failures.append(f"diagnostic logs retained at {run_dir}")

    summary: dict[str, Any] = {
        "schema_version": 1,
        "generated_at_utc": generated_at,
        "provider_mode": (
            "local stand-in for live-mode checks"
            if options.test_local_provider
            else "live Gnani"
            if options.live
            else "local emulated Gnani"
        ),
        "target_duration_seconds": options.duration_s,
        "load_duration_seconds": round(load_duration_s, 3),
        "investigation_count": len(investigations),
        "all_investigations_passed": all_passed,
        "peak_participant_call_sockets": peak_calls,
        "three_call_seconds": round(three_call_seconds, 3),
        "three_call_window": three_call_window,
        "stream_cap_probe": cap_probe,
        "tts_rest_probe": tts_probe,
        "provider": provider_counts,
        "latency": None if options.live else _percentile_fields(investigations),
        "stream_cap_respected": stream_cap_respected,
        "memory_checks_passed": (
            all(item.get("passed") for item in memory_checks) if full_run else None
        ),
        "websocket_closes": {
            "participant_client_count": len(participant_closes),
            "participant_core_count": len(core_call_closes),
            "provider_server_count": len(provider_server_closes),
            "provider_core_count": len(core_provider_closes),
            "unexpected_count": len(unexpected_closes),
            "participant_client": participant_closes,
            "participant_core": [
                {
                    "participant_id": event.get("participant_id"),
                    "investigation_id": event.get("investigation_id"),
                    "code": event.get("socket_close_code"),
                    "reason": event.get("socket_close_reason", ""),
                    "call_reason": event.get("reason"),
                }
                for event in core_call_closes
            ],
            "provider_server": provider_server_closes,
            "provider_core": core_provider_closes,
            "unexpected": unexpected_closes,
        },
        "coverage": paths,
        "memory": {
            "sample_interval_seconds": RSS_SAMPLE_INTERVAL_S,
            "sample_count": len(samples),
            "core": core_rss,
            "sim": sim_rss,
            "core_peak_handles": max(core_handles) if core_handles else None,
            "sim_peak_handles": max(sim_handles) if sim_handles else None,
            "max_governor_peak_streams": max(core_usage_samples) if core_usage_samples else None,
            "max_provider_peak_streams": max(provider_usage_samples)
            if provider_usage_samples
            else provider_final.get("peak_active_websocket_sessions"),
            "sample_errors": sample_errors,
            "leak_checks": memory_checks,
            "slope_limit_mib_per_min": RSS_SLOPE_LIMIT_MIB_PER_MIN,
            "growth_limit_mib": RSS_GROWTH_LIMIT_MIB,
        },
        "investigations": investigations,
        "failures": all_failures,
    }
    if options.live:
        evidence_path = _write_private_live_evidence(options.scratch_root, summary)
        summary["private_evidence_path"] = str(evidence_path)
    if not options.live and options.report_dir is not None:
        _write_report(options.report_dir, summary)
    if not keep_failure_artifacts:
        shutil.rmtree(run_dir, ignore_errors=True)
    if all_failures:
        raise RuntimeError("load run failed:\n- " + "\n- ".join(all_failures))
    return summary
