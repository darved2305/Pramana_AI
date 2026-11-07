"""Servers outlive their clients' idle connections, so a reused connection is never reset."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINTS = [
    ROOT / "services" / "core" / "src" / "pramana_core" / "__main__.py",
    ROOT / "services" / "sim" / "src" / "pramana_sim" / "__main__.py",
    ROOT / "apps" / "web" / "tests-real" / "backend.py",
]


@pytest.mark.parametrize("path", ENTRYPOINTS, ids=lambda p: p.parent.name + "/" + p.name)
def test_every_uvicorn_server_keeps_idle_connections_longer_than_node(path: Path) -> None:
    calls = [
        node
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "uvicorn.run"
    ]
    assert calls, path
    for call in calls:
        keep = {k.arg: k.value for k in call.keywords}.get("timeout_keep_alive")
        assert isinstance(keep, ast.Constant), f"{path}: uvicorn's default 5 s races Node's"
        assert keep.value >= 30
