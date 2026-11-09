"""The rehearsal CLI records an authenticated approver on the real service processes."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from e2e.harness import Services, e2e_database_url
from sqlalchemy.ext.asyncio import create_async_engine

from pramana_contracts import StaffRole
from pramana_core.auth.service import AuthService, LoginThrottle
from pramana_core.db import Database

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "demo rehearsal approver password"


async def _create_approver(email: str) -> str:
    db = Database(create_async_engine(e2e_database_url()))
    try:
        user = await AuthService(db, 3600, LoginThrottle(5, 60)).create_user(
            email,
            "Rehearsal approver",
            PASSWORD,
            [StaffRole.APPROVER],
        )
        return user.id
    finally:
        await db.dispose()


@pytest.mark.e2e
def test_s1_cli_records_the_separately_authenticated_approver(
    services: Services,
    core: httpx.Client,
    tmp_path: Path,
) -> None:
    email = f"approver-{secrets.token_hex(6)}@pramana.test"
    approver_id = asyncio.run(_create_approver(email))
    report_path = tmp_path / "rehearsal.json"
    env = os.environ.copy()
    env.update(
        {
            "CORE_AUTOMATION_KEY": services.automation_key,
            "PRAMANA_APPROVER_EMAIL": email,
            "PRAMANA_APPROVER_PASSWORD": PASSWORD,
            "PYTHONIOENCODING": "utf-8",
        }
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "demo_rehearse.py"),
            "--scenario",
            "S1",
            "--core",
            services.core_url,
            "--sim",
            services.sim_url,
            "--report",
            str(report_path),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        encoding="utf-8",
        text=True,
        timeout=120,
        check=False,
    )

    assert completed.returncode == 0, f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    events = core.get(f"/v1/investigations/{report['investigation_id']}/events").json()
    decisions = [event["payload"] for event in events if event["type"] == "ApprovalDecided"]
    assert len(decisions) == 1
    assert decisions[0]["approver_id"] == approver_id
    assert decisions[0]["approver_id"] != "automation"
    assert "approved by " + approver_id in completed.stdout
    assert report["verification_status"] == "verified"
    assert report["commitment_verified"] is True
    assert report["correct"] is True
    assert report["replay_identical"] is True
