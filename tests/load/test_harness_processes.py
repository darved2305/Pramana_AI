"""Process samples should cover the actual Python service behind a Windows launcher."""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time

import pytest

from load.harness import _process_snapshot, _process_tree_pids


def test_process_tree_selection_includes_nested_worker_processes() -> None:
    parents = {10: 1, 11: 10, 12: 11, 13: 10, 20: 2}

    assert _process_tree_pids(10, parents) == [10, 11, 13, 12]


@pytest.mark.skipif(os.name != "nt", reason="Windows Python uses a launcher process")
def test_process_snapshot_follows_the_python_launcher_to_the_worker() -> None:
    worker = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    try:
        deadline = time.monotonic() + 3
        sample: dict[str, int | None] = {"rss_bytes": None, "handles": None}
        while time.monotonic() < deadline:
            sample = _process_snapshot(worker.pid)
            if sample["rss_bytes"] is not None and sample["rss_bytes"] > 8 * 1024 * 1024:
                break
            time.sleep(0.05)

        assert sample["rss_bytes"] is not None
        assert sample["rss_bytes"] > 8 * 1024 * 1024
    finally:
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(worker.pid)],
            capture_output=True,
            check=False,
        )
        with contextlib.suppress(subprocess.TimeoutExpired):
            worker.wait(timeout=3)
