"""Benchmark reports are served exactly as the harness wrote them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from auth_testkit import login, secure_core
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db
__all__ = ["secure_core"]

SUMMARY = {
    "git_sha": "abc1234",
    "seeds": [10000, 10039],
    "scenario_mix": {"single": 35},
    "policies": {"E_ours": {"n": 40, "success_rate": 0.75}, "B_llm": {"n": 0}},
    "paired_vs_E": {"B_llm": {"success": {"mean": float("nan"), "n": 0.0}}},
}


@pytest.fixture
def reports(core: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    run = tmp_path / "run_a"
    run.mkdir()
    # Python's json writes NaN, as the harness does; the API must still return valid JSON.
    (run / "summary.json").write_text(json.dumps(SUMMARY), encoding="utf-8")
    (tmp_path / "junk").mkdir()
    (tmp_path / "junk" / "summary.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "summary.json").write_text('{"policies": 3}', encoding="utf-8")
    (tmp_path / "secret.json").write_text('{"policies": {}}', encoding="utf-8")
    monkeypatch.setattr(core.app.state.console, "reports_dir", tmp_path)  # type: ignore[attr-defined]
    return tmp_path


def _strict(constant: str) -> None:
    raise AssertionError(f"non-standard JSON constant {constant}")


def test_reports_are_listed_and_served(core: TestClient, reports: Path) -> None:
    listed = core.get("/v1/evaluation/reports").json()
    assert [r["run_id"] for r in listed] == ["run_a"]  # unreadable summaries are skipped
    assert listed[0]["git_sha"] == "abc1234"
    assert listed[0]["policies"] == ["E_ours", "B_llm"]
    r = core.get("/v1/evaluation/reports/run_a")
    assert r.status_code == 200
    json.loads(r.text, parse_constant=_strict)
    summary = r.json()["summary"]
    assert summary["policies"]["E_ours"]["success_rate"] == 0.75
    assert summary["paired_vs_E"]["B_llm"]["success"]["mean"] is None


def test_report_ids_cannot_escape_the_reports_directory(core: TestClient, reports: Path) -> None:
    for bad in ["..", "..%2Fsecret", "%2E%2E", "run_a%2F..%2F..", "a b"]:
        r = core.get(f"/v1/evaluation/reports/{bad}")
        assert r.status_code in (404, 422), (bad, r.status_code)
    assert core.get("/v1/evaluation/reports/missing").status_code == 404
    r = core.get("/v1/evaluation/reports/junk")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_REPORT"


def test_no_reports_directory_is_an_empty_list(
    core: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    console = core.app.state.console  # type: ignore[attr-defined]
    monkeypatch.setattr(console, "reports_dir", tmp_path / "nope")
    assert core.get("/v1/evaluation/reports").json() == []


def test_reports_need_sign_in(secure_core: TestClient) -> None:
    assert secure_core.get("/v1/evaluation/reports").status_code == 401
    login(secure_core, "approver")
    assert secure_core.get("/v1/evaluation/reports").status_code == 200
