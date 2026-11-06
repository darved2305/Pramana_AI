"""Run the production staging stack and restart its owned child processes."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, Protocol
from urllib.parse import urlsplit

from dotenv import dotenv_values

from pramana_core.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = ROOT / "apps" / "web"
CORE_ROOT = ROOT / "services" / "core"
SIM_ROOT = ROOT / "services" / "sim"
ORCH_ROOT = Path(os.environ.get("PRAMANA_ORCH_DIR", Path.home() / "pramana-orch"))
DEFAULT_TOKEN_FILE = ORCH_ROOT / "secrets" / "tunnel_token.txt"
TUNNEL_NAME = "pramana-staging"
CORE_PORT = 8010
SIM_PORT = 8110
WEB_PORT = 3002
GNANI_EMULATOR_PORT = 8099

CORE_ENV_KEYS = {
    str(field.alias or name)
    for name, field in Settings.model_fields.items()
    if isinstance(field.alias or name, str)
}
SIM_ENV_KEYS = {
    "SIM_OPERATOR_KEY",
    "SIM_PARTICIPANT_PUBLIC_KEY",
    "SIM_CORS_ORIGINS",
    "SIM_MAX_SCENARIOS",
    "SIM_HOST",
    "SIM_PORT",
}
WEB_SOURCE_EXCLUDES = {
    ".git",
    ".next",
    ".turbo",
    "coverage",
    "node_modules",
    "playwright-report",
    "test-results",
}
WEB_BUILD_ENV_KEYS = (
    "PRAMANA_CORE_URL",
    "PRAMANA_SIM_URL",
    "NEXT_PUBLIC_ENABLE_PREVIEW",
)
SUPERVISOR_USER_AGENT = "Pramana-Staging-Supervisor/1.0"


def say(message: str) -> None:
    print(message, flush=True)


def normalized_public_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("public origin must be an HTTPS origin without a path")
    return f"https://{parsed.netloc}"


def _open_url(url: str, timeout_s: float) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": SUPERVISOR_USER_AGENT})
    return urllib.request.urlopen(request, timeout=timeout_s)


def _system_environment(inherited: Mapping[str, str]) -> dict[str, str]:
    names = (
        "PATH",
        "SystemRoot",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "TMPDIR",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "HOMEDRIVE",
        "HOMEPATH",
        "PROCESSOR_ARCHITECTURE",
        "PG_BIN",
        "PRAMANA_DB_PORT",
        "PRAMANA_PGDATA",
        "PYTHONIOENCODING",
    )
    return {name: inherited[name] for name in names if name in inherited}


def make_environments(
    source: Mapping[str, str | None],
    public_origin: str,
    *,
    inherited: Mapping[str, str] | None = None,
    root: Path = ROOT,
    fake_gnani: bool = False,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Build isolated core, simulator and web environments from the private .env values."""
    origin = normalized_public_origin(public_origin)
    host_environment = os.environ if inherited is None else inherited
    merged = {key: value for key, value in source.items() if value is not None}
    relevant_keys = CORE_ENV_KEYS | SIM_ENV_KEYS | {"PRAMANA_PACKS_DIR"}
    for key in relevant_keys:
        if key in host_environment:
            merged[key] = host_environment[key]

    required = (
        "SIM_OPERATOR_KEY",
        "PARTICIPANT_SIGNING_KEY",
        "SIM_PARTICIPANT_PUBLIC_KEY",
        "CORE_AUTOMATION_KEY",
    )
    missing = [key for key in required if not merged.get(key)]
    if missing:
        raise ValueError(f"missing required staging settings: {', '.join(missing)}")

    shared = _system_environment(host_environment)
    core = shared | {key: value for key, value in merged.items() if key in CORE_ENV_KEYS}
    for key in ("LLM_CACHE_DIR", "TTS_CACHE_DIR", "EVAL_REPORTS_DIR"):
        if key in core and not Path(core[key]).is_absolute():
            core[key] = str((root / core[key]).resolve())
    core.update(
        PRAMANA_MODE="demo",
        AUTH_REQUIRED="true",
        SESSION_COOKIE_SECURE="true",
        CORE_HOST="127.0.0.1",
        CORE_PORT=str(CORE_PORT),
        SIM_URL=f"http://127.0.0.1:{SIM_PORT}",
        SIM_PUBLIC_URL=f"{origin}/api/sim",
        CORS_ORIGINS=json.dumps([origin]),
        PYTHONUNBUFFERED="1",
    )
    if fake_gnani:
        core.update(
            GNANI_BASE_URL=f"http://127.0.0.1:{GNANI_EMULATOR_PORT}",
            GNANI_API_KEY="pramana-staging-emulator",
        )

    sim = shared | {key: value for key, value in merged.items() if key in SIM_ENV_KEYS}
    sim.update(
        SIM_HOST="127.0.0.1",
        SIM_PORT=str(SIM_PORT),
        SIM_CORS_ORIGINS=json.dumps([origin]),
        SIM_STATE_FILE=str(root / ".cache" / "staging-sim" / "scenarios.json"),
        PYTHONUNBUFFERED="1",
    )

    web = shared | {
        "NODE_ENV": "production",
        "NEXT_TELEMETRY_DISABLED": "1",
        "NEXT_PUBLIC_ENABLE_PREVIEW": "0",
        "PRAMANA_CORE_URL": f"http://127.0.0.1:{CORE_PORT}",
        "PRAMANA_SIM_URL": f"http://127.0.0.1:{SIM_PORT}",
    }
    return core, sim, web


def http_ok(url: str, timeout_s: float = 2.0) -> bool:
    try:
        with _open_url(url, timeout_s) as response:
            status = int(response.status)
            return 200 <= status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def core_ready(url: str, timeout_s: float = 2.0) -> bool:
    try:
        with _open_url(url, timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
        checks = payload.get("checks", {})
        return bool(
            payload.get("status") == "ready"
            and checks.get("database") == "ok"
            and checks.get("simulator") == "ok"
            and checks.get("packs") == "ok"
        )
    except (urllib.error.URLError, OSError, ValueError, AttributeError):
        return False


def wait_until(
    check: Callable[[], bool],
    *,
    timeout_s: float,
    interval_s: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    deadline = clock() + timeout_s
    while True:
        if check():
            return True
        if clock() >= deadline:
            return False
        sleep(interval_s)


class RunningProcess(Protocol):
    def alive(self) -> bool: ...

    def stop(self, grace_s: float = 8.0) -> None: ...


@dataclass
class ManagedChild:
    name: str
    args: list[str]
    env: dict[str, str]
    cwd: Path = ROOT
    secret_values: tuple[str, ...] = ()
    proc: subprocess.Popen[bytes] | None = field(default=None, init=False)
    _pump: threading.Thread | None = field(default=None, init=False, repr=False)

    def start(self, out: IO[str] | None = None) -> ManagedChild:
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
        self._pump = threading.Thread(target=self._relay, args=(out or sys.stdout,), daemon=True)
        self._pump.start()
        return self

    def _relay(self, out: IO[str]) -> None:
        assert self.proc is not None
        assert self.proc.stdout is not None
        encoding = getattr(out, "encoding", None) or "utf-8"
        for raw in self.proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            for secret in self.secret_values:
                if secret:
                    line = line.replace(secret, "[redacted]")
            message = f"[{self.name}] {line}\n".encode(encoding, "replace").decode(encoding)
            with contextlib.suppress(Exception):
                out.write(message)
                out.flush()

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self, grace_s: float = 8.0) -> None:
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        try:
            if sys.platform == "win32":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(proc.pid, signal.SIGTERM)
        except (OSError, ValueError):
            pass
        try:
            proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    check=False,
                )
            else:
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)


@dataclass(frozen=True)
class RestartPolicy:
    initial_delay_s: float = 1.0
    max_delay_s: float = 30.0
    stable_after_s: float = 60.0

    def __post_init__(self) -> None:
        if self.initial_delay_s < 0 or self.max_delay_s < self.initial_delay_s:
            raise ValueError("restart delays must be non-negative and maximum must cover initial")
        if self.stable_after_s < 0:
            raise ValueError("stable_after_s must be non-negative")

    def delay_for(self, failure_count: int) -> float:
        if failure_count <= 0 or self.initial_delay_s == 0:
            return 0.0
        delay = self.initial_delay_s
        for _ in range(failure_count - 1):
            if delay >= self.max_delay_s:
                return float(self.max_delay_s)
            delay = min(delay * 2, self.max_delay_s)
        return float(delay)


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    start: Callable[[], RunningProcess]
    ready: Callable[[], bool]
    startup_timeout_s: float = 60.0


@dataclass
class ServiceState:
    spec: ServiceSpec
    child: RunningProcess | None = None
    failures: int = 0
    started_at: float | None = None


class Supervisor:
    def __init__(
        self,
        services: Sequence[ServiceSpec],
        *,
        restart_policy: RestartPolicy | None = None,
        poll_interval_s: float = 0.5,
        startup_poll_interval_s: float = 0.25,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = say,
    ) -> None:
        if poll_interval_s <= 0 or startup_poll_interval_s <= 0:
            raise ValueError("poll intervals must be positive")
        self.states = [ServiceState(spec) for spec in services]
        self.restart_policy = restart_policy or RestartPolicy()
        self.poll_interval_s = poll_interval_s
        self.startup_poll_interval_s = startup_poll_interval_s
        self.clock = clock
        self.sleep = sleep
        self.log = log
        self.stopping = False

    def _start_state(self, state: ServiceState) -> None:
        while not self.stopping:
            delay = self.restart_policy.delay_for(state.failures)
            if delay:
                self.log(f"[staging] restarting {state.spec.name} in {delay:g}s")
                self.sleep(delay)
            try:
                child = state.spec.start()
            except Exception as exc:
                state.failures += 1
                self.log(
                    f"[staging] could not start {state.spec.name} ({type(exc).__name__}); retrying"
                )
                continue
            state.child = child

            def check_ready(
                current_child: RunningProcess = child,
                current_spec: ServiceSpec = state.spec,
            ) -> bool:
                return current_child.alive() and current_spec.ready()

            ready = wait_until(
                check_ready,
                timeout_s=state.spec.startup_timeout_s,
                interval_s=self.startup_poll_interval_s,
                clock=self.clock,
                sleep=self.sleep,
            )
            if ready:
                state.started_at = self.clock()
                self.log(f"[staging] {state.spec.name} ready")
                return
            child.stop()
            state.child = None
            state.started_at = None
            state.failures += 1
            self.log(f"[staging] {state.spec.name} did not become ready; retrying")

    def start_all(self) -> None:
        for state in self.states:
            self._start_state(state)
            if self.stopping:
                return

    def poll_once(self) -> None:
        for state in self.states:
            child = state.child
            if child is not None and child.alive():
                continue
            if child is not None:
                child.stop()
                uptime = self.clock() - (
                    state.started_at if state.started_at is not None else self.clock()
                )
                if uptime >= self.restart_policy.stable_after_s:
                    state.failures = 0
                state.failures += 1
                self.log(f"[staging] {state.spec.name} exited; recovering")
            state.child = None
            state.started_at = None
            self._start_state(state)

    def run(self) -> None:
        try:
            self.start_all()
            while not self.stopping:
                self.poll_once()
                self.sleep(self.poll_interval_s)
        finally:
            self.stop()

    def stop(self) -> None:
        self.stopping = True
        for state in reversed(self.states):
            if state.child is not None:
                state.child.stop()
                state.child = None


def _web_source_files(web_root: Path) -> list[Path]:
    return sorted(
        path
        for path in web_root.rglob("*")
        if path.is_file()
        and not any(part in WEB_SOURCE_EXCLUDES for part in path.relative_to(web_root).parts)
    )


def web_build_fingerprint(web_root: Path, env: Mapping[str, str]) -> str:
    digest = hashlib.sha256()
    for path in _web_source_files(web_root):
        relative = path.relative_to(web_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    for key in WEB_BUILD_ENV_KEYS:
        digest.update(key.encode("utf-8"))
        digest.update(b"=")
        digest.update(env.get(key, "").encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def ensure_web_build(
    env: Mapping[str, str],
    *,
    web_root: Path = WEB_ROOT,
    run_command: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> bool:
    """Build production Next.js output only when sources or upstream URLs have changed."""
    next_dir = web_root / ".next"
    marker = next_dir / ".staging-build-fingerprint"
    current = web_build_fingerprint(web_root, env)
    if (
        (next_dir / "BUILD_ID").is_file()
        and marker.is_file()
        and marker.read_text(encoding="ascii").strip() == current
    ):
        say("[staging] production web build is current")
        return False

    npm = shutil.which("npm") or "npm"
    run_command(
        [npm, "run", "build"],
        cwd=web_root,
        env=dict(env),
        check=True,
    )
    if not (next_dir / "BUILD_ID").is_file():
        raise RuntimeError("Next.js build completed without writing .next/BUILD_ID")
    marker.write_text(current + "\n", encoding="ascii")
    return True


def load_private_environment(env_path: Path = ROOT / ".env") -> dict[str, str]:
    if not env_path.is_file():
        raise RuntimeError("missing .env; copy C:\\Users\\Nikhil\\pramana-orch\\env.master first")
    return {key: value for key, value in dotenv_values(env_path).items() if value is not None}


def prepare_shared_database(env: Mapping[str, str]) -> None:
    db_env = dict(env)
    if not db_env.get("PG_BIN"):
        candidate = Path.home() / "scoop" / "apps" / "postgresql" / "current" / "bin"
        if (candidate / "pg_ctl.exe").is_file():
            db_env["PG_BIN"] = str(candidate)
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "dev_db.py"), "start"],
        cwd=ROOT,
        env=db_env,
        check=True,
    )


def apply_migrations(core_env: Mapping[str, str]) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=CORE_ROOT,
        env=dict(core_env),
        check=True,
    )


def validate_tunnel_token(path: Path, *, orch_root: Path = ORCH_ROOT) -> str:
    token_path = path.resolve()
    secrets_dir = (orch_root / "secrets").resolve()
    if not token_path.is_relative_to(secrets_dir):
        raise ValueError("tunnel token file must be under pramana-orch\\secrets")
    if not token_path.is_file():
        raise FileNotFoundError(
            f"missing tunnel token file: {token_path}; "
            "create a Workers VPC tunnel or copy its token there"
        )
    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("tunnel token file is empty")
    return token


def validate_worker_binding(
    config_path: Path = ROOT / "infra" / "staging-worker" / "wrangler.jsonc",
) -> None:
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        services = config["vpc_services"]
        service_id = next(item["service_id"] for item in services if item["binding"] == "ORIGIN")
    except (OSError, json.JSONDecodeError, KeyError, StopIteration, TypeError) as exc:
        raise RuntimeError("Worker VPC binding configuration is missing or invalid") from exc
    if service_id == "00000000-0000-0000-0000-000000000000":
        raise RuntimeError("set the VPC service ID in infra/staging-worker/wrangler.jsonc first")


def cloudflared_tunnel_args(cloudflared: str, token_file: Path) -> list[str]:
    """Build the token-file connector command with global flags before ``run``."""
    return [
        cloudflared,
        "tunnel",
        "--no-autoupdate",
        "--loglevel",
        "warn",
        "run",
        "--token-file",
        str(token_file),
    ]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    public_origin = os.environ.get("PRAMANA_STAGING_PUBLIC_ORIGIN")
    env_path = ROOT / ".env"
    if public_origin is None and env_path.is_file():
        public_origin = dotenv_values(env_path).get("PRAMANA_STAGING_PUBLIC_ORIGIN")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--public-origin", default=public_origin)
    parser.add_argument("--tunnel-token-file", type=Path, default=DEFAULT_TOKEN_FILE)
    parser.add_argument(
        "--fake-gnani",
        action="store_true",
        help="run the local protocol emulator instead of sending requests to Gnani",
    )
    return parser.parse_args(argv)


def production_services(
    core_env: dict[str, str],
    sim_env: dict[str, str],
    web_env: dict[str, str],
    tunnel_env: dict[str, str],
    *,
    public_origin: str,
    token_file: Path,
    token: str,
    fake_gnani: bool = False,
) -> list[ServiceSpec]:
    python = sys.executable
    npm = shutil.which("npm") or "npm"
    cloudflared = shutil.which("cloudflared")
    if cloudflared is None:
        raise RuntimeError("cloudflared is not installed or is not on PATH")
    secret_keys = (
        "GNANI_API_KEY",
        "GROQ_API_KEY",
        "GEMINI_API_KEY",
        "PARTICIPANT_SIGNING_KEY",
        "SIM_OPERATOR_KEY",
        "CORE_AUTOMATION_KEY",
        "SIM_ORACLE_KEY",
        "SIM_PARTICIPANT_PUBLIC_KEY",
        "DATABASE_URL",
    )
    secrets = tuple(
        value for value in (token, *(core_env.get(key, "") for key in secret_keys)) if value
    )

    def child(
        name: str, args: list[str], env: dict[str, str], cwd: Path
    ) -> Callable[[], ManagedChild]:
        return lambda: ManagedChild(name, args, env, cwd, secrets).start()

    services = [
        ServiceSpec(
            "sim",
            child("sim", [python, "-m", "pramana_sim"], sim_env, SIM_ROOT),
            lambda: http_ok(f"http://127.0.0.1:{SIM_PORT}/health"),
        ),
        ServiceSpec(
            "core",
            child("core", [python, "-m", "pramana_core"], core_env, CORE_ROOT),
            lambda: core_ready(f"http://127.0.0.1:{CORE_PORT}/ready"),
            startup_timeout_s=120.0,
        ),
        ServiceSpec(
            "web",
            child("web", [npm, "run", "start"], web_env, WEB_ROOT),
            lambda: http_ok(f"http://127.0.0.1:{WEB_PORT}/"),
            startup_timeout_s=180.0,
        ),
        ServiceSpec(
            "tunnel",
            child(
                "tunnel",
                cloudflared_tunnel_args(cloudflared, token_file),
                tunnel_env,
                ROOT,
            ),
            lambda: core_ready(f"{public_origin}/api/core/ready", timeout_s=5.0),
            startup_timeout_s=120.0,
        ),
    ]
    if fake_gnani:
        services.insert(
            0,
            ServiceSpec(
                "gnani-emulator",
                child(
                    "gnani-emulator",
                    [
                        python,
                        str(ROOT / "scripts" / "gnani_emulator.py"),
                        "--serve",
                        "--port",
                        str(GNANI_EMULATOR_PORT),
                    ],
                    _system_environment(os.environ),
                    ROOT,
                ),
                lambda: http_ok(f"http://127.0.0.1:{GNANI_EMULATOR_PORT}/stats"),
            ),
        )
    return services


def main(argv: Sequence[str] | None = None) -> int:
    options = parse_args(argv)
    if not options.public_origin:
        say("[staging] set PRAMANA_STAGING_PUBLIC_ORIGIN to the deployed HTTPS Worker URL")
        return 2
    try:
        public_origin = normalized_public_origin(options.public_origin)
        validate_worker_binding()
        token = validate_tunnel_token(options.tunnel_token_file)
        settings = load_private_environment()
        core_env, sim_env, web_env = make_environments(
            settings, public_origin, fake_gnani=options.fake_gnani
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        say(f"[staging] {exc}")
        return 2

    tunnel_env = _system_environment(os.environ) | {"NO_AUTOUPDATE": "true"}
    try:
        say("[staging] starting the shared PostgreSQL cluster if needed")
        prepare_shared_database(_system_environment(os.environ))
        say("[staging] applying core migrations")
        apply_migrations(core_env)
        say("[staging] checking the production web build")
        ensure_web_build(web_env)
        services = production_services(
            core_env,
            sim_env,
            web_env,
            tunnel_env,
            public_origin=public_origin,
            token_file=options.tunnel_token_file,
            token=token,
            fake_gnani=options.fake_gnani,
        )
    except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        say(f"[staging] preparation failed ({type(exc).__name__})")
        return 1

    supervisor = Supervisor(services)
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), _interrupt)
    if options.fake_gnani:
        say("[staging] using the local Gnani protocol emulator; no Gnani credentials are forwarded")
    say("[staging] starting services, production web, then the tunnel")
    try:
        supervisor.run()
    except KeyboardInterrupt:
        say("[staging] shutting down owned child processes")
        supervisor.stop()
    return 0


def _interrupt(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


if __name__ == "__main__":
    raise SystemExit(main())
