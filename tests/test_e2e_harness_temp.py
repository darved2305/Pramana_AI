"""Temporary files used by the process-level e2e harness are removed on exit."""

import contextlib
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from e2e.harness import Process, temporary_work_directory


def test_e2e_work_directory_leaves_no_temporary_files(tmp_path: Path) -> None:
    with temporary_work_directory(parent=tmp_path) as work:
        work.joinpath("sim.log").write_text("temporary", encoding="utf-8")

    assert not work.exists()
    assert list(tmp_path.iterdir()) == []


def test_e2e_process_cleanup_removes_logs_held_by_descendants(tmp_path: Path) -> None:
    with temporary_work_directory(parent=tmp_path) as work:
        pid_file = work / "grandchild.pid"
        ready_file = work / "grandchild.ready"
        grandchild_code = (
            f"import time; open({str(ready_file)!r}, 'w', encoding='utf-8').close(); time.sleep(60)"
        )
        parent_code = (
            "import os, subprocess, sys, time\n"
            f"grandchild = subprocess.Popen([sys.executable, '-c', {grandchild_code!r}])\n"
            f"while not os.path.exists({str(ready_file)!r}): time.sleep(0.01)\n"
            f"open({str(pid_file)!r}, 'w', encoding='utf-8').write(str(grandchild.pid))\n"
            "time.sleep(60)\n"
        )
        process = Process(
            "dummy", [sys.executable, "-c", parent_code], dict(os.environ), work, work / "core.log"
        )
        grandchild_pid: int | None = None
        try:
            process.start()
            deadline = time.monotonic() + 10
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert pid_file.exists()
            grandchild_pid = int(pid_file.read_text(encoding="utf-8"))

            process.kill()

            assert _wait_until(lambda: not _pid_is_running(grandchild_pid), timeout_s=5)
        finally:
            process.kill()
            if grandchild_pid is not None and _pid_is_running(grandchild_pid):
                _kill_pid(grandchild_pid)
                assert _wait_until(lambda: not _pid_is_running(grandchild_pid), timeout_s=5)

    assert not work.exists()


def _wait_until(check: Callable[[], bool], *, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return False


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _kill_pid(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, check=False)
    else:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
