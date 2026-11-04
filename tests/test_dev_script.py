"""``scripts/dev.py``: argument parsing, readiness polling and child-process shutdown."""

from __future__ import annotations

import importlib.util
import io
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
