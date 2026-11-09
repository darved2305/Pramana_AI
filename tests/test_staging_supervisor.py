"""Tests for the production staging process supervisor."""

from __future__ import annotations

import importlib.util
import os
import socket
import sys
import time
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "pramana_staging_script", ROOT / "scripts" / "staging.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


staging = _load()


def test_restart_policy_caps_exponential_backoff() -> None:
    policy = staging.RestartPolicy(initial_delay_s=1, max_delay_s=30)

    assert [policy.delay_for(n) for n in range(1, 8)] == [1, 2, 4, 8, 16, 30, 30]
    assert staging.RestartPolicy().delay_for(1026) == 30


def test_production_environment_forces_secure_auth_and_isolates_web_secrets() -> None:
    source = {
        "SIM_OPERATOR_KEY": "sim-operator-secret",
        "PARTICIPANT_SIGNING_KEY": "participant-signing-secret",
        "SIM_PARTICIPANT_PUBLIC_KEY": "participant-public-key",
        "CORE_AUTOMATION_KEY": "automation-secret",
        "GNANI_API_KEY": "gnani-secret",
        "SIM_ORACLE_KEY": "oracle-secret",
        "DATABASE_URL": "postgresql+asyncpg://pramana@localhost:5433/pramana",
    }

    core, sim, web = staging.make_environments(
        source, "https://pramana-staging.account.workers.dev", inherited={}
    )

    assert core["PRAMANA_MODE"] == "demo"
    assert core["AUTH_REQUIRED"] == "true"
    assert core["SESSION_COOKIE_SECURE"] == "true"
    assert core["CORE_HOST"] == "127.0.0.1"
    assert core["SIM_URL"] == "http://127.0.0.1:8110"
    assert core["SIM_PUBLIC_URL"] == ("https://pramana-staging.account.workers.dev/api/sim")
    assert core["GNANI_API_KEY"] == "gnani-secret"
    assert sim["SIM_OPERATOR_KEY"] == "sim-operator-secret"
    assert Path(sim["SIM_STATE_FILE"]).parts[-3:] == (
        ".cache",
        "staging-sim",
        "scenarios.json",
    )
    assert "SIM_ORACLE_KEY" not in sim
    assert web["PRAMANA_CORE_URL"] == "http://127.0.0.1:8010"
    assert web["PRAMANA_SIM_URL"] == "http://127.0.0.1:8110"
    assert "GNANI_API_KEY" not in web
    assert "CORE_AUTOMATION_KEY" not in web
    assert "PARTICIPANT_SIGNING_KEY" not in web


def test_emulated_gnani_environment_does_not_forward_configured_credentials() -> None:
    core, _, _ = staging.make_environments(
        {
            "SIM_OPERATOR_KEY": "sim-key",
            "PARTICIPANT_SIGNING_KEY": "signing-key",
            "SIM_PARTICIPANT_PUBLIC_KEY": "participant-public-key",
            "CORE_AUTOMATION_KEY": "automation-key",
            "GNANI_API_KEY": "configured-key",
            "GNANI_BASE_URL": "https://api.vachana.ai",
        },
        "https://pramana-staging.account.workers.dev",
        inherited={},
        fake_gnani=True,
    )

    assert core["GNANI_BASE_URL"] == "http://127.0.0.1:8099"
    assert core["GNANI_API_KEY"] == "pramana-staging-emulator"


def test_unattended_staging_launcher_uses_the_gnani_emulator() -> None:
    launcher = (ROOT / "scripts" / "staging-start.ps1").read_text(encoding="utf-8")

    assert "uv run python scripts/staging.py --fake-gnani" in launcher
    assert (
        "$env:PRAMANA_STAGING_PUBLIC_ORIGIN = "
        "'https://pramana-staging.pramana-staging-worker.workers.dev'"
    ) in launcher


def test_emulator_starts_before_simulator_core_and_web(monkeypatch: object) -> None:
    monkeypatch.setattr(staging.shutil, "which", lambda _: "cloudflared")  # type: ignore[attr-defined]
    services = staging.production_services(
        {},
        {},
        {},
        {},
        public_origin="https://pramana-staging.account.workers.dev",
        token_file=Path("token.txt"),
        token="test-token",
        fake_gnani=True,
    )

    assert [service.name for service in services] == [
        "gnani-emulator",
        "sim",
        "core",
        "web",
        "tunnel",
    ]


def test_staging_emulator_command_uses_supported_options(monkeypatch: object) -> None:
    monkeypatch.setattr(staging.shutil, "which", lambda _: "cloudflared")  # type: ignore[attr-defined]
    command: list[str] = []

    def capture(self: staging.ManagedChild, _out: object = None) -> staging.ManagedChild:
        command.extend(self.args)
        return self

    monkeypatch.setattr(staging.ManagedChild, "start", capture)  # type: ignore[attr-defined]
    services = staging.production_services(
        {},
        {},
        {},
        {},
        public_origin="https://pramana-staging.account.workers.dev",
        token_file=Path("token.txt"),
        token="test-token",
        fake_gnani=True,
    )

    services[0].start()

    assert command[-3:] == ["--serve", "--port", str(staging.GNANI_EMULATOR_PORT)]


def test_production_build_is_reused_until_source_or_upstream_changes(tmp_path: Path) -> None:
    web_root = tmp_path / "web"
    source = web_root / "src" / "page.tsx"
    source.parent.mkdir(parents=True)
    source.write_text("export default 'one'", encoding="utf-8")
    env = {
        "PRAMANA_CORE_URL": "http://127.0.0.1:8010",
        "PRAMANA_SIM_URL": "http://127.0.0.1:8110",
        "NEXT_PUBLIC_ENABLE_PREVIEW": "0",
    }
    calls = 0

    def build(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        next_dir = web_root / ".next"
        next_dir.mkdir(exist_ok=True)
        (next_dir / "BUILD_ID").write_text("built", encoding="ascii")
        return object()

    assert staging.ensure_web_build(env, web_root=web_root, run_command=build)
    assert not staging.ensure_web_build(env, web_root=web_root, run_command=build)
    assert calls == 1

    source.write_text("export default 'two'", encoding="utf-8")
    assert staging.ensure_web_build(env, web_root=web_root, run_command=build)
    assert calls == 2

    env["PRAMANA_CORE_URL"] = "http://127.0.0.1:8020"
    assert staging.ensure_web_build(env, web_root=web_root, run_command=build)
    assert calls == 3


class FakeProcess:
    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events
        self.running = True

    def alive(self) -> bool:
        return self.running

    def stop(self, grace_s: float = 8.0) -> None:
        self.events.append(f"stop:{self.name}")
        self.running = False


def test_services_start_in_declared_order_and_stop_in_reverse() -> None:
    events: list[str] = []
    services = [
        staging.ServiceSpec(
            name,
            start=lambda name=name: events.append(f"start:{name}") or FakeProcess(name, events),
            ready=lambda name=name: events.append(f"ready:{name}") or True,
            startup_timeout_s=1,
        )
        for name in ("sim", "core", "web", "tunnel")
    ]
    supervisor = staging.Supervisor(services, sleep=lambda _: None)

    supervisor.start_all()
    supervisor.stop()

    assert events == [
        "start:sim",
        "ready:sim",
        "start:core",
        "ready:core",
        "start:web",
        "ready:web",
        "start:tunnel",
        "ready:tunnel",
        "stop:tunnel",
        "stop:web",
        "stop:core",
        "stop:sim",
    ]


def test_cloudflared_options_match_installed_cli_positions() -> None:
    command = staging.cloudflared_tunnel_args("cloudflared", Path("token.txt"))

    assert command == [
        "cloudflared",
        "tunnel",
        "--no-autoupdate",
        "--loglevel",
        "warn",
        "run",
        "--token-file",
        "token.txt",
    ]


def test_supervisor_http_probes_use_descriptive_user_agent(monkeypatch: object) -> None:
    requests: list[object] = []

    class Response:
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"status":"ready","checks":{"database":"ok","simulator":"ok","packs":"ok"}}'

    def open_request(request: object, timeout: float) -> Response:
        del timeout
        requests.append(request)
        return Response()

    monkeypatch.setattr(staging.urllib.request, "urlopen", open_request)  # type: ignore[attr-defined]

    assert staging.http_ok("http://127.0.0.1:8110/health")
    assert staging.core_ready("https://staging.example.workers.dev/api/core/ready")
    assert len(requests) == 2
    assert all(
        request.get_header("User-agent") == staging.SUPERVISOR_USER_AGENT  # type: ignore[attr-defined]
        for request in requests
    )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for(predicate: Callable[[], bool], timeout_s: float = 10) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.025)
    raise AssertionError("condition did not become true before the timeout")


def test_supervisor_restarts_a_killed_child(tmp_path: Path) -> None:
    port = _free_port()
    counter = tmp_path / "starts.txt"
    child_code = "\n".join(
        [
            "from http.server import BaseHTTPRequestHandler, HTTPServer",
            "from pathlib import Path",
            "import sys",
            "port = int(sys.argv[1])",
            "counter = Path(sys.argv[2])",
            "count = int(counter.read_text() if counter.exists() else '0') + 1",
            "counter.write_text(str(count))",
            "class Handler(BaseHTTPRequestHandler):",
            " def do_GET(self):",
            "  self.send_response(200)",
            "  self.send_header('Content-Type', 'application/json')",
            "  self.end_headers()",
            '  self.wfile.write(b\'{"status":"ready"}\')',
            " def log_message(self, *args): pass",
            "HTTPServer(('127.0.0.1', port), Handler).serve_forever()",
        ]
    )
    service = staging.ServiceSpec(
        "probe",
        start=lambda: staging.ManagedChild(
            "probe",
            [sys.executable, "-c", child_code, str(port), str(counter)],
            dict(os.environ),
        ).start(),
        ready=lambda: staging.http_ok(f"http://127.0.0.1:{port}/ready"),
        startup_timeout_s=5,
    )
    supervisor = staging.Supervisor(
        [service],
        restart_policy=staging.RestartPolicy(initial_delay_s=0.01, max_delay_s=0.02),
        poll_interval_s=0.01,
        sleep=time.sleep,
    )

    try:
        supervisor.start_all()
        first_child = supervisor.states[0].child
        assert first_child is not None
        assert first_child.proc is not None
        first_child.proc.kill()
        first_child.proc.wait(timeout=5)

        supervisor.poll_once()
        _wait_for(lambda: counter.exists() and counter.read_text(encoding="utf-8") == "2")
        assert staging.http_ok(f"http://127.0.0.1:{port}/ready")
    finally:
        supervisor.stop()
