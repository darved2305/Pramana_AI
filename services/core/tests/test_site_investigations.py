"""Actual investigation flows through saved-site, membership-scoped HTTP routes."""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from auth_testkit import CSRF, login
from core_testkit import body, core_settings
from fastapi.testclient import TestClient
from participant_bot import run_to_conclusion
from sqlalchemy.exc import DBAPIError
from test_accounts import account_core as account_core
from test_accounts import create
from test_google_auth import sql

from pramana_core import ids
from pramana_core.main import create_app
from pramana_domain.spec_storage import load_spec, spec_digest

pytestmark = pytest.mark.db


class TenantClient:
    """Test-only adapter. The participant bot still makes real scoped HTTP requests."""

    def __init__(self, client: TestClient, workspace: dict[str, Any]) -> None:
        self.client = client
        self.workspace = workspace
        self.root = f"/v1/orgs/{workspace['organization']['slug']}/investigations"

    def post(self, path: str, **kw: Any) -> Any:
        headers = {**CSRF, "Idempotency-Key": uuid.uuid4().hex, **kw.pop("headers", {})}
        return self.client.post(
            path.replace("/v1/investigations", self.root), headers=headers, **kw
        )

    def get(self, path: str, **kw: Any) -> Any:
        return self.client.get(path.replace("/v1/investigations", self.root), **kw)

    def start(self, *, fault: str = "CB_C2_7.tripped", **changes: Any) -> dict[str, Any]:
        request = body(fault=fault)
        request.pop("pack_id")
        request["site_id"] = self.workspace["sandbox_site"]["id"]
        request.update(changes)
        response = self.post("/v1/investigations", json=request)
        assert response.status_code == 201, response.text
        return response.json()


@pytest.mark.parametrize(
    ("fault", "decision"),
    [
        ("CB_C2_7.tripped", "DISPATCH_ELECTRICIAN_DB_C2"),
        ("SW_C2.dead", "IT_ONSITE_SW_C2"),
        ("DNS.down", "IT_FIX_DNS"),
    ],
)
def test_saved_site_diagnosis_reveal_and_exact_cold_replay(
    account_core: TestClient, fault: str, decision: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = account_core
    workspace = create(raw).json()
    scoped = TenantClient(raw, workspace)
    svc = raw.app.state.investigations

    # Fail loudly if any command re-enters the legacy name/file path.
    def no_file(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a saved-site investigation must use its pinned specification")

    monkeypatch.setattr(svc, "model", no_file)
    monkeypatch.setattr("pramana_sim.app.load_pack", no_file)
    initial = scoped.start(fault=fault)
    assert initial["site_id"] == workspace["sandbox_site"]["id"]
    assert initial["site_model_id"] == workspace["sandbox_site"]["current_model_id"]
    assert len(initial["model_sha256"]) == 64
    with TestClient(raw.app.state.sim._http._transport.app) as sim:
        final, path = run_to_conclusion(scoped, sim, initial)  # type: ignore[arg-type]
    assert final["status"] == "decided", final["plan"]["reason"]
    assert final["plan"]["decision_class"] == decision
    assert len(path) <= 8
    svc._cache.clear()
    svc.site_models._compiled.clear()
    cold = scoped.get(f"/v1/investigations/{final['id']}")
    assert cold.status_code == 200, cold.text
    assert cold.json()["belief"] == final["belief"]
    reveal = scoped.post(f"/v1/investigations/{final['id']}/reveal")
    assert reveal.status_code == 200, reveal.text
    assert reveal.json()["ground_truth"]["correct"] is True
    assert reveal.json()["ground_truth"]["reveal"]["commitment_verified"] is True
    replay = scoped.get(f"/v1/investigations/{final['id']}/replay")
    assert replay.status_code == 200, replay.text
    assert replay.json()["identical"] is True
    assert replay.json()["log_intact"] is True


def test_creation_retries_return_one_pinned_investigation(account_core: TestClient) -> None:
    client = TenantClient(account_core, create(account_core).json())
    request = body(fault="SW_C2.dead")
    request.pop("pack_id")
    request["site_id"] = client.workspace["sandbox_site"]["id"]
    headers = {"Idempotency-Key": "saved-investigation-001"}
    first = client.post("/v1/investigations", json=request, headers=headers)
    retry = client.post("/v1/investigations", json=request, headers=headers)
    assert first.status_code == retry.status_code == 201, first.text
    assert first.content == retry.content
    assert retry.headers["idempotent-replayed"] == "true"
    listed = client.get("/v1/investigations")
    assert listed.status_code == 200, listed.text
    assert len(listed.json()["items"]) == 1


def test_cursor_pages_are_stable_bounded_and_bound_to_tenant_and_filters(
    account_core: TestClient, migrated_db: str
) -> None:
    raw = account_core
    workspace = create(raw, name="Cursor Campus", slug="cursor-campus").json()
    scoped = TenantClient(raw, workspace)
    base = scoped.start()
    org_id = ids.decode("org", workspace["organization"]["id"])

    # Two thousand fixtures are inserted in one statement. They copy a valid pinned investigation
    # but need no event log because the list reads its bounded projection only.
    sql(
        migrated_db,
        """
        insert into investigations
          (id, org_id, pack_id, site_id, site_model_id, status, scenario_id,
           commitment, request, outcome, ground_truth, version, created_at, updated_at)
        select 'inv_cursor_' || lpad(g::text, 8, '0'), source.org_id, source.pack_id,
          source.site_id, source.site_model_id, source.status, source.scenario_id,
          source.commitment, source.request, source.outcome, source.ground_truth,
          source.version, source.created_at - make_interval(secs => g),
          source.updated_at - make_interval(secs => g)
        from investigations source cross join generate_series(1, 2000) g
        where source.id = :base and source.org_id = :org
        """,
        {"base": base["id"], "org": org_id},
    )
    expected = [
        row["id"]
        for row in sql(
            migrated_db,
            "select id from investigations where org_id=:org order by created_at desc, id desc",
            {"org": org_id},
        )
    ]

    first = scoped.get("/v1/investigations", params={"limit": 100})
    assert first.status_code == 200, first.text
    first_page = first.json()
    assert len(first_page["items"]) == 100
    assert first_page["next_cursor"]

    # A row inserted ahead of the current position belongs to a fresh traversal, not this one.
    sql(
        migrated_db,
        """
        insert into investigations
          (id, org_id, pack_id, site_id, site_model_id, status, scenario_id,
           commitment, request, outcome, ground_truth, version, created_at, updated_at)
        select 'inv_cursor_newest', org_id, pack_id, site_id, site_model_id, status,
          scenario_id, commitment, request, outcome, ground_truth, version,
          now() + interval '1 day', now() + interval '1 day'
        from investigations where id=:base and org_id=:org
        """,
        {"base": base["id"], "org": org_id},
    )
    received = [item["id"] for item in first_page["items"]]
    cursor = first_page["next_cursor"]
    while cursor:
        response = scoped.get("/v1/investigations", params={"limit": 100, "cursor": cursor})
        assert response.status_code == 200, response.text
        page = response.json()
        assert len(page["items"]) <= 100
        received.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
    assert received == expected
    assert len(received) == len(set(received)) == 2001
    assert "inv_cursor_newest" not in received

    filtered = scoped.get(
        "/v1/investigations", params={"limit": 1, "status": "investigating"}
    ).json()
    assert filtered["next_cursor"]
    other_filter = scoped.get(
        "/v1/investigations",
        params={"limit": 1, "status": "decided", "cursor": filtered["next_cursor"]},
    )
    assert other_filter.status_code == 400, other_filter.text
    assert other_filter.json()["error"]["code"] == "CURSOR_INVALID"

    second = raw.post(
        "/v1/orgs",
        json={"name": "Other Cursor Campus", "slug": "other-cursor-campus"},
        headers={**CSRF, "Idempotency-Key": "second-cursor-workspace-0001"},
    )
    assert second.status_code == 201, second.text
    foreign = raw.get(
        f"/v1/orgs/{second.json()['organization']['slug']}/investigations",
        params={"limit": 1, "cursor": filtered["next_cursor"]},
    )
    assert foreign.status_code == 400, foreign.text
    assert foreign.json()["error"]["code"] == "CURSOR_INVALID"


def test_live_or_unknown_site_is_rejected_before_simulator_access(
    account_core: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = create(account_core).json()
    client = TenantClient(account_core, workspace)
    create_scenario = AsyncMock()
    monkeypatch.setattr(account_core.app.state.sim, "create_scenario", create_scenario)
    request = body()
    request.pop("pack_id")
    for site_id, expected in ((workspace["live_site"]["id"], 409), ("bad-site", 404)):
        request["site_id"] = site_id
        response = client.post("/v1/investigations", json=request)
        assert response.status_code == expected, response.text
    create_scenario.assert_not_called()


def test_existing_investigation_keeps_its_model_when_current_version_changes(
    account_core: TestClient, migrated_db: str
) -> None:
    raw = account_core
    workspace = create(raw).json()
    scoped = TenantClient(raw, workspace)
    first = scoped.start()
    old_model = ids.decode("model", first["site_model_id"])
    new_model = ids.uuid7()
    spec = sql(migrated_db, "select spec from site_models where id=:id", {"id": old_model})[0][
        "spec"
    ]
    for component in spec["components"]:
        if component["id"] in ("AP_3A", "AP_3B"):
            component["poe_from"] = "SW_CORE"
    load_spec(spec)
    sql(
        migrated_db,
        """
        insert into site_models (id,org_id,site_id,version,status,spec,spec_sha256,published_at)
        select :new,org_id,site_id,2,'published',cast(:spec as jsonb),:sha,now()
        from site_models where id=:old
    """,
        {"new": new_model, "old": old_model, "spec": json.dumps(spec), "sha": spec_digest(spec)},
    )
    sql(
        migrated_db,
        "update sites set current_model_id=:new where id=:site",
        {"new": new_model, "site": ids.decode("site", first["site_id"])},
    )
    sql(migrated_db, "update site_models set status='retired' where id=:id", {"id": old_model})
    second = scoped.start()
    assert second["site_model_id"] == ids.encode("model", new_model)
    assert second["model_sha256"] != first["model_sha256"]
    assert second["pack_id"] == first["pack_id"]
    # The second physical layout powers floor 3 from a different switch. The sealed CB7 fault
    # therefore affects its observations differently, despite sharing a human-readable label.
    with TestClient(raw.app.state.sim._http._transport.app) as sim:
        values = []
        for investigation in (first, second):
            token = scoped.post(
                f"/v1/investigations/{investigation['id']}/participants/p_riya/token"
            ).json()
            seen = sim.post(
                f"/sim/v1/scenarios/{token['scenario_id']}/observe",
                json={"probe_id": "wifi_status"},
                headers={"Authorization": f"Bearer {token['token']}"},
            )
            assert seen.status_code == 200, seen.text
            values.append(seen.json()["value"])
    assert values == ["no_network", "connected"]
    svc = raw.app.state.investigations
    svc._cache.clear()
    svc.site_models._compiled.clear()
    cold = scoped.get(f"/v1/investigations/{first['id']}").json()
    assert cold["site_model_id"] == first["site_model_id"]
    assert cold["belief"] == first["belief"]
    assert scoped.get(f"/v1/investigations/{first['id']}/replay").json()["identical"] is True
    with pytest.raises(DBAPIError, match="keeps its original site model"):
        sql(
            migrated_db,
            "update investigations set site_model_id=:new where id=:inv",
            {"new": new_model, "inv": first["id"]},
        )


def test_each_scoped_investigation_route_rejects_other_org_before_body_validation(
    account_core: TestClient,
) -> None:
    raw = account_core
    a = TenantClient(raw, create(raw, slug="first-campus").json())
    investigation = a.start()
    login(raw, "approver")
    b = create(raw, slug="second-campus").json()
    operations = [
        (method, path)
        for path, definition in raw.app.openapi()["paths"].items()
        if path.startswith("/v1/orgs/{org}/investigations")
        for method in definition
        if method in {"get", "post", "patch", "put", "delete"}
    ]
    assert len(operations) == 19  # includes availability and quiet-hours override
    for method, template in operations:
        for org in (a.workspace["organization"]["slug"], b["organization"]["slug"]):
            if "{inv_id}" not in template and org == b["organization"]["slug"]:
                continue  # B may list/create its own resources; resource-specific cases below.
            path = template.format(
                org=org,
                inv_id=investigation["id"],
                approval_id="foreign-approval",
                participant_id="p_riya",
                question_id="q_foreign",
            )
            response = raw.request(method, path, json={}, headers=CSRF)
            assert response.status_code == 404, (method, path, response.text)


def test_owner_cannot_self_approve_a_repair(account_core: TestClient, migrated_db: str) -> None:
    raw = account_core
    workspace = create(raw).json()
    scoped = TenantClient(raw, workspace)
    with TestClient(raw.app.state.sim._http._transport.app) as sim:
        final, _ = run_to_conclusion(scoped, sim, scoped.start())  # type: ignore[arg-type]
    approval = scoped.post(
        f"/v1/investigations/{final['id']}/approvals",
        json={"action": "reset_breaker", "target": "CB_C2_7", "participant_id": "p_imran"},
    )
    assert approval.status_code == 201, approval.text
    aid = approval.json()["approvals"][0]["id"]
    # Even explicitly granting both roles cannot make one's own request self-approvable.
    sql(
        migrated_db,
        "update memberships set roles=ARRAY['owner','operator','approver'] "
        "where org_id=:org and user_id=:user",
        {
            "org": ids.decode("org", workspace["organization"]["id"]),
            "user": raw.user_ids["operator"],
        },
    )
    denied = scoped.post(
        f"/v1/investigations/{final['id']}/approvals/{aid}/decision", json={"decision": "approve"}
    )
    assert denied.status_code == 403, denied.text
    assert denied.json()["error"]["code"] == "SELF_APPROVAL"


def test_saved_site_repair_requires_another_approver_and_verifies_in_the_world(
    account_core: TestClient, migrated_db: str
) -> None:
    raw = account_core
    workspace = create(raw).json()
    scoped = TenantClient(raw, workspace)
    org_id = ids.decode("org", workspace["organization"]["id"])
    sql(
        migrated_db,
        "insert into memberships (org_id,user_id,roles) values (:org,:user,ARRAY['approver'])",
        {"org": org_id, "user": raw.user_ids["approver"]},
    )
    with TestClient(raw.app.state.sim._http._transport.app) as sim:
        final, _ = run_to_conclusion(scoped, sim, scoped.start())  # type: ignore[arg-type]
        root = f"/v1/investigations/{final['id']}"
        asked = scoped.post(
            root + "/approvals",
            json={
                "action": "reset_breaker",
                "target": "CB_C2_7",
                "participant_id": "p_imran",
            },
        )
        assert asked.status_code == 201, asked.text
        aid = asked.json()["approvals"][0]["id"]
        login(raw, "approver")
        approved = scoped.post(root + f"/approvals/{aid}/decision", json={"decision": "approve"})
        assert approved.status_code == 200, approved.text
        assert approved.json()["approvals"][0]["approver_id"] == raw.user_ids["approver"]
        login(raw, "operator")
        grant = scoped.post(
            root + f"/approvals/{aid}/capability", params={"participant_id": "p_imran"}
        )
        assert grant.status_code == 200, grant.text
        token = scoped.post(root + "/participants/p_imran/token").json()
        h = {"Authorization": f"Bearer {token['token']}"}
        sid = token["scenario_id"]
        moved = sim.post(f"/sim/v1/scenarios/{sid}/move", json={"to": "DB_C2_PANEL"}, headers=h)
        assert moved.status_code == 200, moved.text
        acted = sim.post(
            f"/sim/v1/scenarios/{sid}/act",
            headers=h,
            json={
                "action": "reset_breaker",
                "target": "CB_C2_7",
                "capability": grant.json()["capability"],
            },
        )
        assert acted.status_code == 200, acted.text
        reported = scoped.post(
            root + "/interventions", json={"approval_id": aid, "participant_id": "p_imran"}
        )
        assert reported.status_code == 200, reported.text
        assert reported.json()["status"] == "verifying"
        verified, _ = run_to_conclusion(scoped, sim, reported.json())  # type: ignore[arg-type]
        assert verified["status"] == "verified", verified["plan"]["reason"]
        assert verified["belief"]["repair"]["fixed_probability"] >= 0.97
        assert scoped.get(root + "/replay").json()["identical"] is True


def test_database_rejects_foreign_org_model_and_log_references(
    account_core: TestClient, migrated_db: str
) -> None:
    raw = account_core
    a = TenantClient(raw, create(raw, slug="first-campus").json())
    inv = a.start()
    b = raw.post(
        "/v1/orgs",
        json={"slug": "second-campus"},
        headers={**CSRF, "Idempotency-Key": "another-workspace-001"},
    )
    assert b.status_code == 201, b.text
    foreign_org = ids.decode("org", b.json()["organization"]["id"])
    with pytest.raises(DBAPIError, match="investigations_model_pin_fk"):
        sql(
            migrated_db,
            """
            insert into investigations (id,org_id,site_id,site_model_id,pack_id,status,
              scenario_id,commitment,request,version)
            select :new,:org,site_id,site_model_id,pack_id,status,
              scenario_id,commitment,request,version
            from investigations where id=:original
        """,
            {"new": ids.new("inv")[1], "org": foreign_org, "original": inv["id"]},
        )
    with pytest.raises(DBAPIError, match="events_org_investigation_fk"):
        sql(
            migrated_db,
            "insert into events (org_id,investigation_id,type,payload) "
            "values (:org,:inv,'Test','{}')",
            {"org": foreign_org, "inv": inv["id"]},
        )


def test_production_has_no_legacy_file_or_unscoped_investigation_routes(migrated_db: str) -> None:
    cfg = core_settings(
        migrated_db,
        PRAMANA_MODE="production",
        PRAMANA_PII_KEY="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
        AUTH_REQUIRED=True,
        CORE_AUTOMATION_KEY="",
        SESSION_COOKIE_SECURE=True,
        OIDC_ISSUER="https://accounts.google.com",
        OIDC_DISCOVERY_URL="https://accounts.google.com/.well-known/openid-configuration",
        OIDC_REDIRECT_URL="https://pramana.example/api/core/v1/auth/google/callback",
    )
    paths = create_app(cfg).openapi()["paths"]
    assert "/v1/orgs/{org}/investigations" in paths
    # Voice status is personal and holds no tenant data (no spend, no provider address).
    assert "/v1/voice/status" in paths
    for path in paths:
        if path == "/v1/voice/status":
            continue
        assert not path.startswith(
            ("/v1/investigations", "/v1/packs", "/v1/participants", "/v1/evaluation", "/v1/voice")
        ), path
    assert "/v1/orgs/{org}/investigations/{inv_id}/answers/voice" in paths
