"""Workspace export, reversible deletion, and scheduled crypto-shredding."""

from __future__ import annotations

import asyncio
import io
import json
import uuid
import zipfile
from typing import Any

import pytest
from auth_testkit import CSRF, login
from core_testkit import body
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine
from test_accounts import account_core as account_core
from test_accounts import create
from test_google_auth import sql
from test_personal_data import NAME, add_person
from test_personal_data import workspace as person_workspace

from pramana_core import ids
from pramana_core.db import Database
from pramana_core.workspace_lifecycle import purge_deleted_organizations

pytestmark = pytest.mark.db


def _delete(client: TestClient, org: str, name: str, key: str) -> Any:
    return client.request(
        "DELETE",
        f"/v1/orgs/{org}",
        json={"confirmation": name},
        headers={**CSRF, "Idempotency-Key": key},
    )


def test_workspace_lifecycle_and_lists_hide_other_organizations(account_core: TestClient) -> None:
    client = account_core
    foreign = create(client, name="Foreign Workspace", slug="foreign-workspace").json()
    login(client, "approver")
    create(client, name="Own Workspace", slug="own-workspace")
    root = f"/v1/orgs/{foreign['organization']['slug']}"
    site = foreign["live_site"]["id"]
    operations = [
        ("GET", f"{root}/export"),
        ("DELETE", root),
        ("POST", f"{root}/restore"),
        ("GET", f"{root}/investigations?cursor=invalid"),
        ("GET", f"{root}/sites?cursor=invalid"),
        ("GET", f"{root}/sites/{site}/models?cursor=invalid"),
        ("GET", f"{root}/sites/{site}/people?cursor=invalid"),
        ("GET", f"{root}/members?cursor=invalid"),
        ("GET", f"{root}/invitations?cursor=invalid"),
    ]
    for method, path in operations:
        response = client.request(
            method,
            path,
            json={},
            headers={**CSRF, "Idempotency-Key": "foreign-workspace-check-01"},
        )
        assert response.status_code == 404, (method, path, response.text)


def test_deleted_workspace_is_closed_to_members_and_owner_can_restore(
    account_core: TestClient, migrated_db: str
) -> None:
    client = account_core
    workspace = create(client, name="Restore Campus").json()
    org = workspace["organization"]
    org_id = ids.decode("org", org["id"])
    sql(
        migrated_db,
        "insert into memberships (org_id,user_id,roles) values (:org,:user,array['viewer'])",
        {"org": org_id, "user": client.user_ids["approver"]},  # type: ignore[attr-defined]
    )

    wrong = _delete(client, org["slug"], org["name"] + "x", "delete-wrong-name-0001")
    assert wrong.status_code == 422, wrong.text
    assert wrong.json()["error"]["code"] == "WORKSPACE_NAME_MISMATCH"
    assert client.get(f"/v1/orgs/{org['slug']}").status_code == 200

    deleted = _delete(client, org["slug"], org["name"], "delete-campus-restore-01")
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["purge_after"]
    retry = _delete(client, org["slug"], org["name"], "delete-campus-restore-01")
    assert retry.content == deleted.content
    assert retry.headers["idempotent-replayed"] == "true"
    assert client.get(f"/v1/orgs/{org['slug']}").status_code == 410
    assert client.get(f"/v1/orgs/{org['slug']}/sites").status_code == 410
    me = client.get("/v1/me")
    assert me.status_code == 200, me.text
    assert me.json()["destination"] == "/onboarding/welcome"
    assert len(me.json()["memberships"]) == 1
    assert me.json()["memberships"][0]["deleted_at"] is not None

    login(client, "approver")
    member = client.get(f"/v1/orgs/{org['slug']}/sites")
    assert member.status_code == 410, member.text
    owner_action = client.get(f"/v1/orgs/{org['slug']}/export")
    assert owner_action.status_code == 403, owner_action.text
    assert (
        client.post(
            f"/v1/orgs/{org['slug']}/restore",
            headers={**CSRF, "Idempotency-Key": "viewer-cannot-restore-01"},
        ).status_code
        == 403
    )

    login(client, "operator")
    archived = client.get(f"/v1/orgs/{org['slug']}/export")
    assert archived.status_code == 200, archived.text
    assert archived.headers["content-type"] == "application/zip"
    restore = client.post(
        f"/v1/orgs/{org['slug']}/restore",
        headers={**CSRF, "Idempotency-Key": "restore-campus-window-01"},
    )
    assert restore.status_code == 200, restore.text
    assert restore.json()["deleted_at"] is None
    assert client.get(f"/v1/orgs/{org['slug']}/sites").status_code == 200
    actions = sql(
        migrated_db,
        "select action from audit_log where org_id=:org order by ts, id",
        {"org": org_id},
    )
    assert [row["action"] for row in actions][-3:] == [
        "organization.deleted",
        "organization.exported",
        "organization.restored",
    ]


def test_export_stream_contains_only_the_owner_workspace_data(
    account_core: TestClient, migrated_db: str
) -> None:
    client = account_core
    org, org_ref, site = person_workspace(client)
    add_person(client, org, site)
    sql(
        migrated_db,
        """
        insert into site_people (org_id,site_id,id,spec,display_name_enc,version)
        select org_id,site_id,'legacy-person',
          jsonb_set(spec,'{display_name}',to_jsonb(cast(:name as text))),null,version
        from site_people where org_id=:org and id='ananya'
        """,
        {"org": ids.decode("org", org_ref), "name": "Legacy Person"},
    )
    other = client.post(
        "/v1/orgs",
        json={"name": "Other Private Workspace", "slug": "other-private-workspace"},
        headers={**CSRF, "Idempotency-Key": "create-other-export-space-01"},
    )
    assert other.status_code == 201, other.text

    response = client.get(f"/v1/orgs/{org}/export")
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        assert names == {
            "workspace.json",
            "sites.json",
            "site_models.json",
            "people.json",
            "consents.json",
            "investigations.json",
            "questions.json",
            "observations.json",
            "approvals.json",
            "events.json",
            "members.json",
            "invitations.json",
            "audit_log.json",
        }
        payloads = {name: archive.read(name) for name in names}
    workspace_data = json.loads(payloads["workspace.json"])
    people = json.loads(payloads["people.json"])
    audit = json.loads(payloads["audit_log.json"])
    assert workspace_data[0]["slug"] == org
    names = {row["person_id"]: row for row in people}
    assert names["ananya"]["name"] == NAME
    assert names["ananya"]["spec"]["display_name"] == NAME
    assert names["legacy-person"]["name"] == "Legacy Person"
    assert any(row["action"] == "organization.exported" for row in audit)
    all_data = b"\n".join(payloads.values())
    assert b"Other Private Workspace" not in all_data
    assert b"token_hash" not in all_data
    assert b"wrapped_key" not in all_data
    assert b"session" not in all_data.lower()
    assert b"oauth" not in all_data.lower()


def test_due_purge_shreds_person_data_and_preserves_other_workspace_replay(
    account_core: TestClient, migrated_db: str
) -> None:
    client = account_core
    first = create(client, name="Purge Campus", slug="purge-campus").json()
    second = client.post(
        "/v1/orgs",
        json={"name": "Replay Campus", "slug": "replay-campus"},
        headers={**CSRF, "Idempotency-Key": "create-replay-workspace-001"},
    )
    assert second.status_code == 201, second.text
    workspaces = [first, second.json()]
    investigation_ids: list[str] = []
    for workspace_data in workspaces:
        organization = workspace_data["organization"]
        request = body(fault="CB_C2_7.tripped")
        request.pop("pack_id")
        request["site_id"] = workspace_data["sandbox_site"]["id"]
        created = client.post(
            f"/v1/orgs/{organization['slug']}/investigations",
            json=request,
            headers={**CSRF, "Idempotency-Key": f"create-inv-{uuid.uuid4().hex}"},
        )
        assert created.status_code == 201, created.text
        investigation_ids.append(created.json()["id"])

    replay_path = (
        f"/v1/orgs/{workspaces[1]['organization']['slug']}/investigations/"
        f"{investigation_ids[1]}/replay"
    )
    replay_before = client.get(replay_path)
    assert replay_before.status_code == 200, replay_before.text
    assert replay_before.json()["identical"] is True

    export = client.get(f"/v1/orgs/{first['organization']['slug']}/export")
    assert export.status_code == 200, export.text
    with zipfile.ZipFile(io.BytesIO(export.content)) as archive:
        investigations = json.loads(archive.read("investigations.json"))
        questions = json.loads(archive.read("questions.json"))
        events = json.loads(archive.read("events.json"))
    assert investigations[0]["id"] == investigation_ids[0]
    assert investigations[0]["report"]["text"] == body()["report"]["text"]
    assert investigations[0]["participants"][0]["display_name"] == "Riya"
    assert questions
    assert events

    org_id = ids.decode("org", first["organization"]["id"])
    deleted = _delete(
        client,
        first["organization"]["slug"],
        first["organization"]["name"],
        "delete-purge-campus-0001",
    )
    assert deleted.status_code == 200, deleted.text
    before_events = sql(
        migrated_db,
        "select count(*) as n from events where org_id=:org",
        {"org": org_id},
    )[0]["n"]
    sql(
        migrated_db,
        "update organizations set purge_after=now()-interval '31 days' where id=:org",
        {"org": org_id},
    )
    assert client.get(f"/v1/orgs/{first['organization']['slug']}/export").status_code == 410
    assert (
        client.post(
            f"/v1/orgs/{first['organization']['slug']}/restore",
            headers={**CSRF, "Idempotency-Key": "restore-after-deadline-01"},
        ).status_code
        == 410
    )

    async def purge() -> int:
        engine = create_async_engine(migrated_db)
        try:
            return await purge_deleted_organizations(Database(engine))
        finally:
            await engine.dispose()

    assert asyncio.run(purge()) == 1
    org_state = sql(
        migrated_db,
        "select purged_at, slug from organizations where id=:org",
        {"org": org_id},
    )[0]
    assert org_state["purged_at"] is not None
    assert org_state["slug"].startswith("purged-")
    assert (
        sql(
            migrated_db,
            "select count(*) as n from person_keys where org_id=:org",
            {"org": org_id},
        )[0]["n"]
        == 0
    )
    for table in ("questions", "observations", "approvals", "consents", "invitations"):
        assert (
            sql(
                migrated_db, f"select count(*) as n from {table} where org_id=:org", {"org": org_id}
            )[0]["n"]
            == 0
        )
    assert (
        sql(
            migrated_db,
            "select count(*) as n from site_people where org_id=:org",
            {"org": org_id},
        )[0]["n"]
        == 0
    )
    assert (
        sql(
            migrated_db,
            "select count(*) as n from personal_texts where org_id=:org",
            {"org": org_id},
        )[0]["n"]
        == 0
    )
    assert (
        sql(
            migrated_db,
            "select count(*) as n from memberships where org_id=:org",
            {"org": org_id},
        )[0]["n"]
        == 0
    )
    assert (
        sql(
            migrated_db,
            "select count(*) as n from events where org_id=:org",
            {"org": org_id},
        )[0]["n"]
        == before_events
    )
    unsafe = sql(
        migrated_db,
        """
        select count(*) as n from events where org_id=:org and
          ((type='ReportReceived' and payload->>'text' not in ('-', '')) or
           (type='InvestigationCreated' and exists (
             select 1 from jsonb_array_elements(payload->'participants') p
             where coalesce(p->>'display_name','') not in ('-', ''))))
        """,
        {"org": org_id},
    )[0]["n"]
    assert unsafe == 0
    assert (
        sql(
            migrated_db,
            "select count(*) as n from audit_log "
            "where org_id=:org and action='organization.purged'",
            {"org": org_id},
        )[0]["n"]
        == 1
    )

    replay_after = client.get(replay_path)
    assert replay_after.status_code == 200, replay_after.text
    assert replay_after.content == replay_before.content
