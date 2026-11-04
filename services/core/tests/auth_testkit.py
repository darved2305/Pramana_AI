"""A core with sign-in enforced, plus users to sign in as."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import httpx
import pytest
from core_testkit import core_settings, truncate_all
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from pramana_contracts import StaffRole
from pramana_core.auth.service import AuthService, LoginThrottle
from pramana_core.db import Database
from pramana_core.main import create_app

AUTOMATION_KEY = "test-automation-key"
PASSWORD = "correct horse battery"
CSRF = {"X-Pramana-CSRF": "1"}
USERS = {
    "operator": ("op@pramana.test", "Olu Operator", [StaffRole.OPERATOR]),
    "approver": ("ap@pramana.test", "Asha Approver", [StaffRole.APPROVER]),
    "both": ("both@pramana.test", "Bo Both", [StaffRole.OPERATOR, StaffRole.APPROVER]),
}


async def _seed(db_url: str) -> dict[str, str]:
    db = Database(create_async_engine(db_url))
    try:
        svc = AuthService(db, 3600, LoginThrottle(5, 60))
        ids = {}
        for name, (email, display, roles) in USERS.items():
            ids[name] = (await svc.create_user(email, display, PASSWORD, roles)).id
        return ids
    finally:
        await db.dispose()


@pytest.fixture
def secure_core(migrated_db: str, sim_app: FastAPI) -> Iterator[TestClient]:
    asyncio.run(truncate_all(migrated_db))
    ids = asyncio.run(_seed(migrated_db))
    app = create_app(
        core_settings(
            migrated_db,
            AUTH_REQUIRED=True,
            CORE_AUTOMATION_KEY=AUTOMATION_KEY,
            LOGIN_MAX_FAILURES=3,
        ),
        sim_transport=httpx.ASGITransport(app=sim_app),
    )
    with TestClient(app) as client:
        client.user_ids = ids  # type: ignore[attr-defined]
        client.sim_app = sim_app  # type: ignore[attr-defined]
        yield client


def login(client: TestClient, who: str) -> TestClient:
    email = USERS[who][0]
    r = client.post("/v1/auth/login", json={"email": email, "password": PASSWORD}, headers=CSRF)
    assert r.status_code == 200, r.text
    return client


AUTO = {"X-Automation-Key": AUTOMATION_KEY}
