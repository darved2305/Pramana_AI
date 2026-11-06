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
DEFAULT_SCRATCH = Path(r"C:\Users\Nikhil\pramana-orch\scratch\p3")
RSS_SAMPLE_INTERVAL_S = 5.0
RSS_SLOPE_LIMIT_MIB_PER_MIN = 1.0
RSS_GROWTH_LIMIT_MIB = 32.0
CAP_PROBE_STREAM_LIMIT = 2
ALLOWED_CALL_CLOSE_CODES = {1000, 4408}
ALLOWED_PROVIDER_CLOSE_CODES = {1000}


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
    if not target.database or not re.fullmatch(r"pramana_load_p3(?:_[a-z0-9]+)?", target.database):
        raise ValueError("load database name must start with pramana_load_p3")

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
) -> dict[str, Any]:
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
    if result.returncode != 0:
        tail = "\n".join((result.stdout + result.stderr).splitlines()[-80:])
        raise RuntimeError(f"voice bot run failed with exit code {result.returncode}:\n{tail}")
    if options.live:
        return {"live_run_completed": True}
    lines = result.stdout.splitlines()
    summary_line = next(
        (
            line.removeprefix("LOAD_RESULT_JSON=")
            for line in reversed(lines)
            if line.startswith("LOAD_RESULT_JSON=")
        ),
        None,
    )
    if summary_line is None:
        raise RuntimeError("voice bot run did not emit its load result")
    return json.loads(summary_line)


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
        f"Time with three participant call sockets open: "
        f"{summary['three_call_seconds']:.1f} seconds.",
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


async def run_load(options: LoadOptions) -> dict[str, Any]:
    _validate_options(options)
    if options.live and not _load_key_configured():
        raise RuntimeError("live mode requires GNANI_API_KEY in the environment or worktree .env")
    ports = [options.core_port, options.sim_port]
    if not options.live:
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
    fake_url = None if options.live else f"http://127.0.0.1:{options.fake_port}"
    fake_event_log = run_dir / "provider-events.jsonl"

    base_env = os.environ.copy()
    base_env["PYTHONIOENCODING"] = "utf-8"
    base_env["PYTHONUNBUFFERED"] = "1"
    await asyncio.to_thread(_ensure_postgres_and_database, options.database_url, base_env)

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
        stream_cap=CAP_PROBE_STREAM_LIMIT if not options.live else options.stream_cap,
    )
    fake_process: ManagedProcess | None = None
    if not options.live:
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
    workload_started = 0.0
    failure: BaseException | None = None

    try:
        if fake_process is not None:
            fake_process.start()
            _wait_http(fake_process, f"{fake_url}/health")
        sim_process.start()
        _wait_http(sim_process, f"{sim_url}/health")
        core_process.start()
        _wait_http(core_process, f"{core_url}/ready")

        if fake_url is not None:
            cap_probe = await _probe_stream_cap(core_url, automation_key)
            core_process.stop()
            core_env["GNANI_MAX_STREAMS"] = str(options.stream_cap)
            core_process.start()
            _wait_http(core_process, f"{core_url}/ready")

        tts_probe = await _tts_rest_probe(core_url, automation_key)
        workload_started = time.monotonic()
        sample_task = asyncio.create_task(
            _sample_runtime(
                core=core_process,
                sim=sim_process,
                core_url=core_url,
                fake_url=fake_url,
                automation_key=automation_key,
                started=workload_started,
                stop=sample_stop,
                samples=samples,
                sample_errors=sample_errors,
            )
        )

        first = await asyncio.to_thread(
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
            bot_log=logs / "voice-bots.log",
        )
        if not options.live:
            investigations.append(first)

        while time.monotonic() - workload_started < options.duration_s or (
            not options.live
            and sum(
                float((item.get("call_socket_metrics") or {}).get("three_way_seconds", 0))
                for item in investigations
            )
            < options.duration_s
        ):
            delay = 4.0 if len(investigations) == 1 else 0.0
            result = await asyncio.to_thread(
                _run_bot,
                options=options,
                run_dir=run_dir,
                core_url=core_url,
                sim_url=sim_url,
                automation_key=automation_key,
                parallel=3,
                silent_first=False,
                delay_first_answer_s=delay,
                barge_in_first=len(investigations) == 2 and not options.live,
                keep_calls_open=True,
                idle_probe=False,
                bot_log=logs / "voice-bots.log",
            )
            if not options.live:
                investigations.append(result)

        sample_stop.set()
        if sample_task is not None:
            await sample_task
            sample_task = None

        if fake_url is not None:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                headers = {"X-Automation-Key": automation_key}
                async with (
                    httpx.AsyncClient(base_url=fake_url, timeout=5) as provider_client,
                    httpx.AsyncClient(base_url=core_url, headers=headers, timeout=5) as core_client,
                ):
                    provider_final = await _json_get(provider_client, "/metrics")
                    usage_final = await _json_get(core_client, "/v1/voice/usage")
                if (
                    provider_final.get("active_websocket_sessions") == 0
                    and usage_final.get("open_streams") == 0
                ):
                    break
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("provider streams remained open after the call bots finished")
        else:
            provider_final = {}
            usage_final = {}
    except BaseException as exc:
        failure = exc
        sample_stop.set()
        if sample_task is not None:
            sample_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sample_task
            sample_task = None
    finally:
        for process in reversed(processes):
            process.stop()

    load_duration_s = max(0.0, time.monotonic() - workload_started) if workload_started else 0.0
    core_call_closes = _structured_events(logs / "core.log", "call_ended")
    core_provider_closes = _structured_events(logs / "core.log", "gnani_ws_closed")
    participant_closes = [
        {"investigation_id": investigation.get("investigation_id"), **close}
        for investigation in investigations
        for close in investigation.get("call_socket_closes", [])
    ]
    provider_server_closes = (
        list(provider_final.get("websocket_close_events", [])) if not options.live else []
    )
    unexpected_closes: list[dict[str, Any]] = []
    for close in participant_closes:
        if close.get("code") not in ALLOWED_CALL_CLOSE_CODES:
            unexpected_closes.append({"side": "participant_client", **close})
    for close in core_call_closes:
        if close.get("socket_close_code") not in ALLOWED_CALL_CLOSE_CODES:
            unexpected_closes.append({"side": "participant_core", **close})
    for close in provider_server_closes:
        if close.get("code") not in ALLOWED_PROVIDER_CLOSE_CODES:
            unexpected_closes.append({"side": "fake_provider_server", **close})
    for close in core_provider_closes:
        if close.get("code") not in ALLOWED_PROVIDER_CLOSE_CODES:
            unexpected_closes.append({"side": "core_provider_client", **close})

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

    peak_calls = max(
        [
            int((item.get("call_socket_metrics") or {}).get("peak_open", 0))
            for item in investigations
        ]
        or [0]
    )
    three_call_seconds = sum(
        float((item.get("call_socket_metrics") or {}).get("three_way_seconds", 0))
        for item in investigations
    )
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
    if not options.live:
        if not isinstance(cap_probe, dict) or not cap_probe.get("refused_at_cap"):
            all_failures.append("lower stream-cap sub-run did not refuse the over-cap request")
        if cap_probe and (
            cap_probe.get("open_streams_when_full") != 2
            or cap_probe.get("peak_streams_when_full") != 2
            or cap_probe.get("max_streams") != 2
        ):
            all_failures.append("lower stream-cap sub-run did not hold exactly two streams")
        if cap_probe and any(
            item.get("code") != 1000 for item in cap_probe.get("client_socket_closes", [])
        ):
            all_failures.append("a stream-cap probe WebSocket closed unexpectedly")
        if provider_final.get("websocket_sessions_opened") != provider_final.get(
            "websocket_sessions_closed"
        ):
            all_failures.append("fake provider WebSocket sessions did not all close")
        if len(core_provider_closes) != int(provider_final.get("websocket_sessions_closed", 0)):
            all_failures.append("core and fake provider WebSocket close counts differ")
        if tts_probe is None or tts_probe.get("status") != 200:
            all_failures.append("TTS REST probe did not pass")
        if provider_final.get("tts_rest_requests", 0) < 1:
            all_failures.append("fake provider did not receive a TTS REST request")
        if provider_final.get("tts_sse_requests", 0) < 1:
            all_failures.append("fake provider did not receive a TTS SSE request")
        if int(usage_final.get("peak_streams", 0)) > options.stream_cap:
            all_failures.append("governor peak exceeded its configured stream cap")
        if int(provider_final.get("peak_active_websocket_sessions", 0)) > options.stream_cap:
            all_failures.append("fake provider observed more streams than the governor cap")
        if not investigations:
            all_failures.append("no S1 investigations completed")
        if not all_passed:
            all_failures.append(
                "an investigation was not correct, verified, commitment-checked, "
                "and replay-identical"
            )
        if peak_calls < 3:
            all_failures.append("three participant call sockets were never open at once")
        if three_call_seconds < options.duration_s:
            all_failures.append(
                "three-way call socket time did not reach the requested load duration"
            )
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
            all_failures.append("unexpected WebSocket close code or reason was observed")
        if len(participant_closes) != len(core_call_closes):
            all_failures.append("participant and core call WebSocket close counts differ")
        if sample_errors:
            all_failures.append(f"runtime metric sampling errors: {sample_errors[:5]}")
        if full_run and not all(item.get("passed") for item in memory_checks):
            all_failures.append("RSS growth exceeded the configured leak thresholds")
    else:
        if any(close.get("code") not in ALLOWED_CALL_CLOSE_CODES for close in participant_closes):
            all_failures.append("live participant WebSocket had an unexpected close code")
        if unexpected_closes:
            all_failures.append("live core-side WebSocket close code was unexpected")

    keep_failure_artifacts = bool(
        all_failures and os.environ.get("PRAMANA_LOAD_KEEP_FAILURE_ARTIFACTS") == "1"
    )
    if keep_failure_artifacts:
        all_failures.append(f"diagnostic logs retained at {run_dir}")

    summary: dict[str, Any] = {
        "schema_version": 1,
        "generated_at_utc": generated_at,
        "provider_mode": "live Gnani" if options.live else "local emulated Gnani",
        "target_duration_seconds": options.duration_s,
        "load_duration_seconds": round(load_duration_s, 3),
        "investigation_count": len(investigations),
        "all_investigations_passed": all_passed,
        "peak_participant_call_sockets": peak_calls,
        "three_call_seconds": round(three_call_seconds, 3),
        "stream_cap_probe": cap_probe,
        "tts_rest_probe": tts_probe,
        "provider": provider_counts,
        "latency": None if options.live else _percentile_fields(investigations),
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
            "provider_core": [
                {"code": event.get("code"), "reason": event.get("reason", "")}
                for event in core_provider_closes
            ],
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
    if not options.live and options.report_dir is not None:
        _write_report(options.report_dir, summary)
    if not keep_failure_artifacts:
        shutil.rmtree(run_dir, ignore_errors=True)
    if all_failures:
        raise RuntimeError("load run failed:\n- " + "\n- ".join(all_failures))
    return summary
