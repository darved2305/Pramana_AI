"""Pack listing."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db


def test_pack_list_matches_the_pack_detail(core: TestClient) -> None:
    packs = core.get("/v1/packs").json()
    campus = next(p for p in packs if p["id"] == "campus_block_c")
    detail = core.get("/v1/packs/campus_block_c").json()
    assert campus["locations"] == len(detail["locations"])
    assert campus["probes"] == len(detail["probes"])
    assert campus["title"] == detail["title"]
    assert campus["version"] == detail["version"]


def test_invalid_pack_files_are_not_offered(
    core: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "broken.yaml").write_text("pack: broken\nversion: [", encoding="utf-8")
    (tmp_path / "half.yaml").write_text("pack: half\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")
    monkeypatch.setattr(core.app.state.console, "packs_dir", tmp_path)  # type: ignore[attr-defined]
    assert core.get("/v1/packs").json() == []
