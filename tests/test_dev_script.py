"""``scripts/dev.py``: argument parsing, readiness polling and child-process shutdown."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pramana_dev_script", ROOT / "scripts" / "dev.py")
    assert spec is not None
    assert spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(mod)
    return mod


dev = _load()


def test_defaults_match_the_documented_ports() -> None:
    o = dev.parse_args([])
    assert (o.core_port, o.sim_port, o.web_port, o.web, o.skip_db) == (
        8000,
        8100,
        3002,
        False,
        False,
    )


def test_ports_and_flags_are_parsed() -> None:
    o = dev.parse_args(["--web", "--core-port", "8030", "--sim-port", "8130", "--web-port", "3012"])
    assert (o.core_port, o.sim_port, o.web_port, o.web) == (8030, 8130, 3012, True)


@pytest.mark.parametrize(
    "argv",
    [
        ["--core-port", "8100"],  # collides with the simulator default
        ["--web", "--web-port", "8000"],
        ["--core-port", "0"],
        ["--sim-port", "70000"],
        ["--core-port", "abc"],
        ["--timeout", "0"],
    ],
)
def test_invalid_arguments_are_refused(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        dev.parse_args(argv)
    assert exc.value.code == 2


def test_web_port_may_equal_another_when_web_is_off() -> None:
    assert dev.parse_args(["--web-port", "8000"]).web is False


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.t += s


def test_wait_until_succeeds_once_the_check_passes() -> None:
    clock, calls = FakeClock(), []

    def check() -> bool:
        calls.append(clock.t)
        return len(calls) >= 3

    assert dev.wait_until(check, timeout_s=10, interval_s=1, clock=clock.now, sleep=clock.sleep)
    assert calls == [0.0, 1.0, 2.0]


def test_wait_until_times_out() -> None:
    clock = FakeClock()
    ok = dev.wait_until(
        lambda: False, timeout_s=2.5, interval_s=1, clock=clock.now, sleep=clock.sleep
    )
    assert ok is False
    assert clock.t == pytest.approx(3.0)


def test_wait_until_gives_up_when_the_process_dies() -> None:
    clock = FakeClock()
    ok = dev.wait_until(
        lambda: False,
        timeout_s=60,
        alive=lambda: clock.t < 2,
        interval_s=1,
        clock=clock.now,
        sleep=clock.sleep,
    )
    assert ok is False
    assert clock.t == pytest.approx(2.0)  # did not wait for the full minute


def test_http_ok_against_a_real_socket() -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200 if self.path == "/health" else 503)
            self.end_headers()

        def log_message(self, *_: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert dev.http_ok(f"http://127.0.0.1:{port}/health")
        assert not dev.http_ok(f"http://127.0.0.1:{port}/ready")  # 503 is not ready
    finally:
        server.shutdown()
        server.server_close()
    assert not dev.http_ok(f"http://127.0.0.1:{port}/health", timeout_s=0.5)  # closed port


def test_service_env_points_the_core_at_the_chosen_simulator() -> None:
    env = dev.service_env(dev.parse_args(["--core-port", "8030", "--sim-port", "8130"]), {})
    assert env["SIM_URL"] == "http://127.0.0.1:8130"
    assert env["CORE_PORT"] == "8030"
    assert env["SIM_PORT"] == "8130"
    assert env["PRAMANA_CORE_URL"] == "http://127.0.0.1:8030"
    assert "http://localhost:3002" in env["CORS_ORIGINS"]


def test_service_env_keeps_explicit_cors_settings() -> None:
    env = dev.service_env(dev.parse_args([]), {"CORS_ORIGINS": '["https://x"]'})
    assert env["CORS_ORIGINS"] == '["https://x"]'


def test_main_returns_success_when_interrupted_during_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupted(_opts: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(dev.signal, "signal", lambda *_: None)
    monkeypatch.setattr(dev, "prepare", interrupted)

    assert dev.main([]) == 0


def test_web_child_only_with_flag() -> None:
    env: dict[str, str] = {}
    assert [c.name for c in dev.children(dev.parse_args([]), env)] == ["sim", "core"]
    with_web = dev.children(dev.parse_args(["--web"]), env)
    assert [c.name for c in with_web] == ["sim", "core", "web"]
    assert with_web[2].cwd == ROOT / "apps" / "web"


def test_child_output_is_prefixed_and_stop_ends_the_process() -> None:
    script = "import time\nprint('hello', flush=True)\ntime.sleep(60)\n"
    out = io.StringIO()
    child = dev.Child("demo", [sys.executable, "-c", script], dict(__import__("os").environ))
    child.start(out)
    assert dev.wait_until(lambda: "[demo] hello" in out.getvalue(), timeout_s=20)
    assert child.alive()
    started = time.monotonic()
    child.stop(grace_s=5)
    assert not child.alive()
    assert time.monotonic() - started < 15
    child.stop()  # stopping twice is harmless


def test_stop_ends_a_child_tree_even_when_a_descendant_ignores_graceful_shutdown(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "grandchild.pid"
    ready_file = tmp_path / "grandchild.ready"
    grandchild_code = (
        "import signal, time\n"
        "signal.signal(getattr(signal, 'SIGBREAK', signal.SIGTERM), signal.SIG_IGN)\n"
        f"open({str(ready_file)!r}, 'w', encoding='utf-8').close()\n"
        "time.sleep(60)\n"
    )
    parent_code = (
        "import os, signal, subprocess, sys, time\n"
        f"grandchild = subprocess.Popen([sys.executable, '-c', {grandchild_code!r}], "
        "creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))\n"
        f"while not os.path.exists({str(ready_file)!r}): time.sleep(0.01)\n"
        f"open({str(pid_file)!r}, 'w', encoding='utf-8').write(str(grandchild.pid))\n"
        "print('tree ready', flush=True)\n"
        "time.sleep(0.1)\n"
    )
    out = io.StringIO()
    child = dev.Child("tree", [sys.executable, "-c", parent_code], dict(os.environ))
    grandchild_pid: int | None = None
    try:
        child.start(out)
        assert dev.wait_until(
            lambda: pid_file.exists() and "[tree] tree ready" in out.getvalue(), timeout_s=10
        )
        grandchild_pid = int(pid_file.read_text(encoding="utf-8"))
        assert child.proc is not None
        assert child.proc.wait(timeout=10) == 0
        assert _pid_is_running(grandchild_pid)

        child.stop(grace_s=2)

        assert dev.wait_until(lambda: not _pid_is_running(grandchild_pid), timeout_s=5)
    finally:
        child.stop(grace_s=0.2)
        if grandchild_pid is not None and _pid_is_running(grandchild_pid):
            _kill_pid(grandchild_pid)


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _kill_pid(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
            check=False,
        )
        return
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)


def test_output_the_console_cannot_encode_never_freezes_a_child() -> None:
    # Next.js prints "▲"; a cp1252 console cannot encode it. The relay used to die on it, the
    # child's pipe then filled, and the web server froze. Far more than a pipe's worth here.
    code = "import sys\nfor _ in range(4000): print('\u25b2 Next.js ready ' + 'x' * 40)\n"
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    child = dev.Child("web", [sys.executable, "-c", code], env=dict(os.environ))
    child.start(out)
    assert child.proc is not None
    assert child.proc.wait(timeout=20) == 0  # it finished: the pipe was drained
    assert child._pump is not None
    child._pump.join(timeout=5)
    out.flush()
    written = out.buffer.getvalue()  # type: ignore[attr-defined]
    assert written.count(b"Next.js ready") == 4000
    assert b"? Next.js" in written  # the unencodable character was replaced, not fatal


def test_service_env_loads_selected_database_from_checkout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql+asyncpg://local/selected\nPRAMANA_DB_NAMES=selected\n",
        encoding="utf-8",
    )
    assert dev.service_env(dev.Options(), {})["DATABASE_URL"].endswith("/selected")


def test_service_env_requires_database(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="DATABASE_URL"):
        dev.service_env(dev.Options(), {})


def test_service_env_refuses_a_process_database_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql+asyncpg://local/selected\nPRAMANA_DB_NAMES=selected\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="DATABASE_URL in the process environment conflicts"):
        dev.service_env(dev.Options(), {"DATABASE_URL": "postgresql+asyncpg://local/other"})


def test_service_env_refuses_a_database_outside_the_checkout_allowlist(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql+asyncpg://local/other\nPRAMANA_DB_NAMES=selected\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not listed in PRAMANA_DB_NAMES"):
        dev.service_env(dev.Options(), {})


def test_demo_uses_local_mock_identity_and_emulator(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql+asyncpg://localhost/safe\nPRAMANA_DB_NAMES=safe\n",
        encoding="utf-8",
    )
    opts = dev.parse_args(["--demo"])
    env = dev.service_env(opts, {})
    assert opts.web
    assert env["OIDC_ISSUER"] == "http://localhost:8410"
    assert env["GNANI_API_KEY"] == "local-emulator"
    assert env["GNANI_BASE_URL"] == "http://127.0.0.1:8099"
    assert env["SIM_STATE_FILE"] == ""
    assert [child.name for child in dev.children(opts, env)] == [
        "oidc",
        "gnani-emulator",
        "sim",
        "core",
        "web",
    ]


def test_demo_rejects_a_remote_database(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql+asyncpg://remote.example/db\nPRAMANA_DB_NAMES=db\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="local database"):
        dev.service_env(dev.parse_args(["--demo"]), {})


def test_demo_rejects_a_database_url_without_a_name(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql+asyncpg://localhost\nPRAMANA_DB_NAMES=safe\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="database name"):
        dev.service_env(dev.parse_args(["--demo"]), {})
