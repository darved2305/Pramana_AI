"""The take sheet is filled from a real investigation's records, never typed by hand."""

from __future__ import annotations

import csv
import sys
from argparse import Namespace
from pathlib import Path

import pytest
from core_testkit import body
from fastapi.testclient import TestClient
from participant_bot import run_to_conclusion
from test_closing_loop import approve, decided, reset_in_simulator, verify

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
import take_log

pytestmark = pytest.mark.db


def _args(inv_id: str, scenario: str = "S1") -> Namespace:
    return Namespace(
        investigation=inv_id,
        scenario=scenario,
        seed="7",
        participants="bot",
        deployment="local",
        take_id=None,
        recording=None,
        notes="in-process test",
    )


def test_a_verified_take_is_logged_from_the_core(core: TestClient, tmp_path: Path) -> None:
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    inv = decided(core, sim, "CB_C2_7.tripped")
    with pytest.raises(take_log.TakeError, match="reveal it in the same take"):
        take_log.take_row(core, _args(inv["id"]), commit="abc", clean=True)
    _, aid = approve(core, inv)
    reset_in_simulator(core, sim, inv["id"], aid)
    state = core.post(
        f"/v1/investigations/{inv['id']}/interventions",
        json={"approval_id": aid, "participant_id": "p_imran"},
    ).json()
    assert verify(core, sim, state)["status"] == "verified"
    core.post(f"/v1/investigations/{inv['id']}/reveal")

    row = take_log.take_row(core, _args(inv["id"]), commit="abc", clean=True)
    assert row["status_before_reveal"] == "verified"
    assert row["decision"] == "DISPATCH_ELECTRICIAN_DB_C2"
    assert row["repair_verified"] is True
    assert row["correct_on_reveal"] is True
    assert row["commitment_verified"] is True
    assert row["replay_identical"] is True
    assert row["commitment"] == inv["sealed_commitment"]
    assert row["voice_provider"].startswith("gnani")
    sheet = tmp_path / "take-sheet.csv"
    take_log.append(row, sheet)
    take_log.append(row, sheet)
    rows = list(csv.DictReader(sheet.open(encoding="utf-8")))
    assert len(rows) == 2
    assert list(rows[0]) == take_log.COLUMNS


def test_an_abstention_is_logged_as_one(core: TestClient) -> None:
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    people = [
        {**p, "skill": "lay", "roles": ["student"]} if p["id"] != "p_riya" else p
        for p in body()["participants"]
    ]
    r = core.post("/v1/investigations", json=body(fault="SW_C2.dead", people=people))
    final, _ = run_to_conclusion(core, sim, r.json(), max_steps=25)
    core.post(f"/v1/investigations/{final['id']}/reveal")
    row = take_log.take_row(core, _args(final["id"], "S7"), commit="abc", clean=False)
    assert row["status_before_reveal"] == final["status"]
    if final["status"] == "abstained":
        assert row["decision"] == "abstained"
        assert row["correct_on_reveal"] is None
    assert row["worktree_clean"] is False
