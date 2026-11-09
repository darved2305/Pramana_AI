"""Workspace setup, retry safety and two-tab autosave against real PostgreSQL and RLS."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import httpx
import pytest
from auth_testkit import CSRF, _seed, login
from core_testkit import core_settings, truncate_all
from fastapi import APIRouter, FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from test_google_auth import sql

from pramana_core import ids
from pramana_core.account_rows import OnboardingRow
from pramana_core.db import Database, OrganizationRow, acting_for
from pramana_core.errors import ApiError
from pramana_core.idempotency import IdempotencyRoute, idempotent, reap_expired
from pramana_core.main import create_app
from pramana_core.org_access import require_user
from pramana_domain.spec_storage import load_spec
from pramana_engine import compile_pack

pytestmark = pytest.mark.db
KEY = "workspace-create-001"
HEADERS = {**CSRF, "Idempotency-Key": KEY}


@pytest.fixture(params=["owner", "runtime"])
def account_core(
    request: pytest.FixtureRequest, migrated_db: str, sim_app: FastAPI
) -> Iterator[TestClient]:
    asyncio.run(truncate_all(migrated_db))
    user_ids = asyncio.run(_seed(migrated_db))
    url = migrated_db
    if request.param == "runtime":
        url = (
            make_url(url)
            .set(username="pramana_app", password=None)
            .render_as_string(hide_password=False)
        )
    app = create_app(
        core_settings(url, AUTH_REQUIRED=True, CORE_AUTOMATION_KEY=""),
        sim_transport=httpx.ASGITransport(app=sim_app),
    )
    test_routes = APIRouter(route_class=IdempotencyRoute)

    @test_routes.post("/v1/orgs/{org}/test-mutation")
    @idempotent("org", roles=("owner",))
    async def mutate(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        access = request.state.organization
        with acting_for(access.organization.id, access.principal.id):
            async with app.state.db.transaction() as session:
                org = await session.get(OrganizationRow, access.organization.id)
                assert org is not None
                org.version += 1
                await session.flush()
                if body.get("error"):
                    raise ApiError(409, "TEST_REJECTED", "the test action was rejected")
                if body.get("crash"):
                    raise RuntimeError("test crash after a flushed mutation")
                return {"version": org.version, "payload": body}

    # A handled error after a joined flush must roll back before caching the error response.
    @test_routes.post("/v1/test-personal-mutation")
    @idempotent("user")
    async def personal(request: Request, body: dict[str, Any]) -> dict[str, Any]:
        principal = await require_user(request)
        with acting_for(None, principal.id):
            async with app.state.db.transaction() as session:
                row = await session.get(OnboardingRow, principal.id)
                assert row is not None
                row.step = "survey"
                await session.flush()
                raise ApiError(409, "TEST_REJECTED", "the test action was rejected")

    app.include_router(test_routes)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.user_ids = user_ids  # type: ignore[attr-defined]
        yield login(client, "operator")


def create(client: TestClient, **body: Any) -> Any:
    response = client.post("/v1/orgs", json=body or {"name": "Test campus"}, headers=HEADERS)
    assert response.status_code == 201, response.text
    return response


def test_me_starts_private_resumable_state(account_core: TestClient) -> None:
    client = account_core
    me = client.get("/v1/me")
    assert me.status_code == 200, me.text
    assert me.headers["cache-control"] == "no-store"
    assert me.json()["destination"] == "/onboarding/welcome"
    assert me.json()["memberships"] == []
    assert me.json()["identities"] == []
    assert me.json()["onboarding"]["version"] == 1
    assert client.get("/v1/onboarding").headers["etag"] == '"1"'
    assert client.get("/v1/me").json()["onboarding"]["version"] == 1


def test_or_09_create_org_once_after_lost_response(
    account_core: TestClient, migrated_db: str
) -> None:
    client = account_core
    response = create(client)
    data = response.json()
    assert data["organization"]["roles"] == ["operator", "owner"]
    assert data["sandbox_site"]["mode"] == "sandbox"
    assert data["sandbox_site"]["current_model_id"].startswith("model_")
    assert data["live_site"]["mode"] == "live"
    assert data["live_site"]["current_model_id"] is None
    retry = create(client)
    assert retry.content == response.content
    assert retry.headers["idempotent-replayed"] == "true"
    assert retry.headers["cache-control"] == "no-store"
    org = data["organization"]
    assert (
        sql(
            migrated_db,
            "select count(*) as n from organizations where slug = :slug",
            {"slug": org["slug"]},
        )[0]["n"]
        == 1
    )
    me = client.get("/v1/me").json()
    assert me["destination"] == "/onboarding/sandbox"
    assert me["memberships"][0]["id"] == org["id"]
    assert me["preferences"]["last_org_id"] == org["id"]
    assert client.get(f"/v1/orgs/{org['id']}").json() == org
    assert client.get(f"/v1/orgs/{org['slug']}").json() == org


def test_stored_sandbox_is_identical_to_latest_frozen_template(
    account_core: TestClient, migrated_db: str
) -> None:
    data = create(account_core).json()
    assert data["sandbox_site"]["kind"] == "other"
    model_id = ids.decode("model", data["sandbox_site"]["current_model_id"])
    rows = sql(
        migrated_db,
        "select m.spec, m.spec_sha256, t.spec as template, "
        "t.spec_sha256 as template_hash from site_models m cross join model_templates t "
        "where m.id = :id and t.purpose = 'sandbox' order by t.version desc limit 1",
        {"id": model_id},
    )
    assert rows[0]["spec"] == rows[0]["template"]
    digest = hashlib.sha256(
        json.dumps(
            rows[0]["spec"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).digest()
    assert digest == rows[0]["spec_sha256"] == rows[0]["template_hash"]

    templates = sql(
        migrated_db,
        "select version, spec, spec_sha256 from model_templates "
        "where purpose = 'sandbox' order by version",
    )
    assert [row["version"] for row in templates] == [1, 2]
    frozen_v1_digest = hashlib.sha256(
        json.dumps(
            templates[0]["spec"], ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).digest()
    assert bytes(templates[0]["spec_sha256"]).hex() == (
        "9435216bfb330b2da94db1166a9e4147613536e224897cbc5b8f1b2485a75837"
    )
    assert frozen_v1_digest == templates[0]["spec_sha256"]
    assert templates[0]["spec"]["title"] == "Hostel Block C (simulated)"

    spec = templates[1]["spec"]
    compile_pack(load_spec(spec))
    copy = [spec["title"]]
    copy.extend(role["label"] for role in spec["roles"])
    copy.extend(location["label"]["en"] for location in spec["locations"])
    copy.extend(component["label"] for component in spec["components"])
    copy.extend(
        failure["label"]
        for component in spec["components"]
        for failure in component["failure_modes"]
    )
    copy.extend(probe["label"] for probe in spec["probes"])
    copy.extend(text for probe in spec["probes"] for text in probe["templates"].values())
    copy.extend(decision["label"] for decision in spec["decision_classes"])
    shown = " ".join(copy).casefold()
    for site_specific_term in (
        "hostel",
        "guard desk",
        "student",
        "nava-wifi",
        "wifi",
        "wi-fi",
        "वाई-फ़ाई",
        "वाय-फाय",
        "ip test page",
        "bookmark",
        "ont",
        "pon",
        "idf-",
        "db-c2",
        "isp",
        "dhcp",
        "dns",
        "cctv",
        "nvr",
        "poe",
        "hvac",
        "access point",
        "rack",
        "main-1",
        "c2-5",
        "c2-7",
        "gateway",
    ):
        assert re.search(rf"\b{re.escape(site_specific_term)}\b", shown) is None


@pytest.mark.parametrize(
    "key", [None, "short", "has spaces in the key", "a" * 129, '"unclosed-key-00001']
)
def test_idempotency_key_errors(account_core: TestClient, key: str | None) -> None:
    headers = dict(CSRF)
    if key is not None:
        headers["Idempotency-Key"] = key
    response = account_core.post("/v1/orgs", json={}, headers=headers)
    assert response.status_code == 400, response.text


def test_key_accepts_quoted_form_and_canonical_json(account_core: TestClient) -> None:
    first = account_core.post(
        "/v1/orgs",
        content='{"name":"Campus", "kind":"campus"}',
        headers={**HEADERS, "Content-Type": "application/json"},
    )
    assert first.status_code == 201, first.text
    retry = account_core.post(
        "/v1/orgs",
        content='{"kind": "campus", "name": "Campus"}',
        headers={**HEADERS, "Idempotency-Key": f'"{KEY}"', "Content-Type": "application/json"},
    )
    assert retry.content == first.content
    assert retry.headers["idempotent-replayed"] == "true"


def test_key_reuse_changed_body_or_path_or_query_is_422(account_core: TestClient) -> None:
    create(account_core)
    for path, body in [
        ("/v1/orgs", {"name": "Different"}),
        ("/v1/orgs?x=1", {}),
        ("/v1/onboarding", {"step": "survey"}),
    ]:
        response = (account_core.patch if "onboarding" in path else account_core.post)(
            path, json=body, headers=HEADERS
        )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_or_10_two_tabs_conflict_then_reload(account_core: TestClient) -> None:
    client = account_core
    first = client.get("/v1/onboarding")
    second = client.get("/v1/onboarding")
    assert first.headers["etag"] == second.headers["etag"]
    saved = client.patch(
        "/v1/onboarding",
        json={"answers": {"work": "it"}, "step": "survey"},
        headers={**HEADERS, "If-Match": first.headers["etag"]},
    )
    assert saved.status_code == 200, saved.text
    replay = client.patch(
        "/v1/onboarding",
        json={"answers": {"work": "it"}, "step": "survey"},
        headers={**HEADERS, "If-Match": first.headers["etag"]},
    )
    assert replay.content == saved.content
    assert replay.headers["etag"] == saved.headers["etag"] == '"2"'
    stale = client.patch(
        "/v1/onboarding",
        json={"answers": {"problem": "power"}},
        headers={
            **HEADERS,
            "Idempotency-Key": "other-tab-save-001",
            "If-Match": second.headers["etag"],
        },
    )
    assert stale.status_code == 412, stale.text
    assert stale.json()["error"]["details"]["current_version"] == 2
    latest = client.get("/v1/onboarding")
    retry = client.patch(
        "/v1/onboarding",
        json={"answers": {"problem": "power"}},
        headers={
            **HEADERS,
            "Idempotency-Key": "other-tab-save-002",
            "If-Match": latest.headers["etag"],
        },
    )
    assert retry.status_code == 200, retry.text
    assert retry.json()["answers"]["work"] == "it"
    assert retry.json()["answers"]["problem"] == "power"
    assert client.get("/v1/me").json()["destination"] == "/onboarding/survey"


def test_form_version_required_and_future_step_guard(account_core: TestClient) -> None:
    missing = account_core.patch("/v1/onboarding", json={}, headers=HEADERS)
    assert missing.status_code == 428, missing.text
    invalid_step = account_core.patch(
        "/v1/onboarding",
        json={"step": "sandbox"},
        headers={**HEADERS, "Idempotency-Key": "future-step-00001", "If-Match": '"1"'},
    )
    assert invalid_step.status_code == 409, invalid_step.text
    assert account_core.get("/v1/onboarding").json()["version"] == 1


def test_complete_or_dismiss_routes_to_active_org(account_core: TestClient) -> None:
    org = create(account_core).json()["organization"]
    current = account_core.get("/v1/onboarding")
    response = account_core.patch(
        "/v1/onboarding",
        json={"dismissed": True},
        headers={
            **HEADERS,
            "Idempotency-Key": "dismiss-form-0001",
            "If-Match": current.headers["etag"],
        },
    )
    assert response.status_code == 200, response.text
    assert account_core.get("/v1/me").json()["destination"] == f"/app/{org['slug']}"


def test_unverified_user_cannot_create_org(account_core: TestClient, migrated_db: str) -> None:
    uid = account_core.get("/v1/me").json()["user"]["user_id"]
    sql(migrated_db, "update users set email_verified_at = null where id = :id", {"id": uid})
    response = account_core.post("/v1/orgs", json={}, headers=HEADERS)
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "EMAIL_VERIFICATION_REQUIRED"


def test_personal_state_and_idempotency_are_per_user(account_core: TestClient) -> None:
    a = create(account_core).json()["organization"]
    login(account_core, "approver")
    me = account_core.get("/v1/me").json()
    assert me["memberships"] == []
    assert me["preferences"]["last_org_id"] is None
    assert account_core.get(f"/v1/orgs/{a['id']}").status_code == 404
    assert account_core.get(f"/v1/orgs/{a['slug']}").status_code == 404
    b = create(account_core).json()["organization"]
    assert a["id"] != b["id"]
    assert b["roles"] == ["operator", "owner"]


def test_slug_conflict_is_replayable_and_has_suggestions(
    account_core: TestClient, migrated_db: str
) -> None:
    create(account_core, name="A", slug="shared-campus")
    headers = {**HEADERS, "Idempotency-Key": "slug-conflict-0001"}
    response = account_core.post(
        "/v1/orgs", json={"name": "B", "slug": "shared-campus"}, headers=headers
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["details"]["suggestions"]
    retry = account_core.post(
        "/v1/orgs", json={"name": "B", "slug": "shared-campus"}, headers=headers
    )
    assert retry.content == response.content
    assert retry.headers["idempotent-replayed"] == "true"
    assert sql(migrated_db, "select count(*) as n from organizations where name = 'B'")[0]["n"] == 0


def test_org_scopes_and_authorization_before_replay(
    account_core: TestClient, migrated_db: str
) -> None:
    a = create(account_core).json()["organization"]
    b = account_core.post(
        "/v1/orgs", json={"name": "B"}, headers={**HEADERS, "Idempotency-Key": "second-workspace-1"}
    ).json()["organization"]
    for org in (a, b):
        response = account_core.post(
            f"/v1/orgs/{org['id']}/test-mutation", json={"n": 1}, headers=HEADERS
        )
        assert response.status_code == 200, response.text
        assert response.json()["version"] == 2
    org_id = ids.decode("org", a["id"])
    sql(
        migrated_db,
        "update memberships set roles = array['viewer'] where org_id = :id",
        {"id": org_id},
    )
    assert (
        account_core.post(
            f"/v1/orgs/{a['id']}/test-mutation", json={"n": 1}, headers=HEADERS
        ).status_code
        == 403
    )
    sql(migrated_db, "delete from memberships where org_id = :id", {"id": org_id})
    assert (
        account_core.post(
            f"/v1/orgs/{a['id']}/test-mutation", json={"n": 1}, headers=HEADERS
        ).status_code
        == 404
    )


def test_removed_member_state_is_repaired(account_core: TestClient, migrated_db: str) -> None:
    org = create(account_core).json()["organization"]
    previous = account_core.get("/v1/onboarding")
    sql(
        migrated_db,
        "delete from memberships where org_id = :id",
        {"id": ids.decode("org", org["id"])},
    )
    save = account_core.patch(
        "/v1/onboarding",
        json={"answers": {"problem": "wifi"}},
        headers={
            **HEADERS,
            "Idempotency-Key": "removed-member-save-1",
            "If-Match": previous.headers["etag"],
        },
    )
    assert save.status_code == 409, save.text
    assert save.json()["error"]["code"] == "MEMBERSHIP_CHANGED"
    me = account_core.get("/v1/me")
    assert me.status_code == 200, me.text
    assert me.json()["destination"] == "/onboarding/welcome"
    assert me.json()["memberships"] == []
    assert me.json()["onboarding"]["org_id"] is None


def test_handled_error_rolls_back_flushed_business_state(account_core: TestClient) -> None:
    account_core.get("/v1/me")
    response = account_core.post("/v1/test-personal-mutation", json={}, headers=HEADERS)
    assert response.status_code == 409, response.text
    assert account_core.get("/v1/me").json()["onboarding"]["step"] == "welcome"
    assert (
        account_core.post("/v1/test-personal-mutation", json={}, headers=HEADERS).content
        == response.content
    )


def test_unhandled_error_rolls_back_and_releases_claim(
    account_core: TestClient, migrated_db: str
) -> None:
    org = create(account_core).json()["organization"]
    path = f"/v1/orgs/{org['id']}/test-mutation"
    assert account_core.post(path, json={"crash": True}, headers=HEADERS).status_code == 500
    assert account_core.get(f"/v1/orgs/{org['id']}").json()["version"] == 1
    assert (
        sql(
            migrated_db,
            "select count(*) as n from idempotency_keys where org_id = :id",
            {"id": ids.decode("org", org["id"])},
        )[0]["n"]
        == 0
    )
    response = account_core.post(path, json={"ok": True}, headers=HEADERS)
    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2


@pytest.mark.parametrize("lease_seconds", [60, -1])
def test_or_09_simultaneous_create_returns_in_flight_then_replays(
    account_core: TestClient, monkeypatch: pytest.MonkeyPatch, migrated_db: str, lease_seconds: int
) -> None:
    client = account_core
    service = client.app.state.accounts  # type: ignore[union-attr]
    original = service.create_organization
    monkeypatch.setattr("pramana_core.idempotency.LEASE", timedelta(seconds=lease_seconds))
    entered = threading.Event()
    release = threading.Event()

    async def slow(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        await asyncio.to_thread(release.wait, 10)
        return await original(*args, **kwargs)

    monkeypatch.setattr(service, "create_organization", slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, "/v1/orgs", json={"name": "Concurrent"}, headers=HEADERS)
        try:
            assert entered.wait(10)
            pending = client.post("/v1/orgs", json={"name": "Concurrent"}, headers=HEADERS)
            assert pending.status_code == 409, pending.text
            assert pending.json()["error"]["code"] == "IDEMPOTENCY_IN_FLIGHT"
        finally:
            release.set()
        completed = first.result(timeout=15)
    assert completed.status_code == 201, completed.text
    retry = client.post("/v1/orgs", json={"name": "Concurrent"}, headers=HEADERS)
    assert retry.content == completed.content
    assert (
        sql(migrated_db, "select count(*) as n from organizations where name = 'Concurrent'")[0][
            "n"
        ]
        == 1
    )


def test_workspace_and_response_roll_back_together_after_handler_failure(
    account_core: TestClient, monkeypatch: pytest.MonkeyPatch, migrated_db: str
) -> None:
    client = account_core
    client.get("/v1/me")
    service = client.app.state.accounts  # type: ignore[union-attr]
    original = service.create_organization

    async def crash(*args: Any, **kwargs: Any) -> Any:
        await original(*args, **kwargs)
        raise RuntimeError("failed before storing the response")

    monkeypatch.setattr(service, "create_organization", crash)
    response = client.post("/v1/orgs", json={"name": "Atomic"}, headers=HEADERS)
    assert response.status_code == 500, response.text
    assert (
        sql(migrated_db, "select count(*) as n from organizations where name='Atomic'")[0]["n"] == 0
    )
    assert (
        sql(migrated_db, "select count(*) as n from audit_log where action='organization.created'")[
            0
        ]["n"]
        == 0
    )
    assert sql(migrated_db, "select count(*) as n from idempotency_keys")[0]["n"] == 0
    assert client.get("/v1/me").json()["onboarding"]["step"] == "welcome"
    monkeypatch.setattr(service, "create_organization", original)
    assert create(client, name="Atomic").status_code == 201


def test_expired_pending_claim_recovers_and_72_hour_reaper_is_scoped(
    account_core: TestClient, migrated_db: str
) -> None:
    client = account_core
    uid = client.get("/v1/me").json()["user"]["user_id"]
    # Simulate an instance dying after committing its pending claim, before business work.
    sql(
        migrated_db,
        "insert into idempotency_keys "
        "(scope,principal,key,method,path,request_sha256,owner_nonce,locked_until) "
        "values (:actor,:actor,:key,'POST','/v1/orgs',:hash,:nonce,now() - interval '1 minute')",
        {
            "actor": f"user:{uid}",
            "key": KEY,
            "nonce": uuid.uuid4(),
            "hash": hashlib.sha256(b'POST\n/v1/orgs\n{"name":"Recovered"}').digest(),
        },
    )
    retry = create(client, name="Recovered")
    assert retry.headers.get("idempotent-replayed") is None
    assert retry.json()["organization"]["name"] == "Recovered"
    sql(migrated_db, "update idempotency_keys set created_at = now() - interval '73 hours'")
    login(client, "approver")
    create(client)
    db: Database = client.app.state.db  # type: ignore[union-attr]

    async def reap() -> int:
        with acting_for(None, uid):
            return await reap_expired(db)

    assert client.portal is not None
    assert client.portal.call(reap) == 1
    assert sql(migrated_db, "select count(*) as n from idempotency_keys")[0]["n"] == 1


def test_reaper_skips_an_active_transaction_even_after_72_hours(
    account_core: TestClient, migrated_db: str
) -> None:
    client = account_core
    uid = client.get("/v1/me").json()["user"]["user_id"]
    create(client)
    sql(migrated_db, "update idempotency_keys set created_at = now() - interval '73 hours'")
    db: Database = client.app.state.db  # type: ignore[union-attr]

    async def check() -> None:
        with acting_for(None, uid):
            async with db.transaction() as session:
                await session.execute(text("select * from idempotency_keys for update"))
                assert await asyncio.create_task(reap_expired(db)) == 0
            assert await reap_expired(db) == 1

    assert client.portal is not None
    client.portal.call(check)
