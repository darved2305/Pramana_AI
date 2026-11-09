"""Consent links and availability decisions for synthetic live-site investigations."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from auth_testkit import CSRF
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_accounts import account_core as account_core
from test_google_auth import sql
from test_practice import published_water_site
from test_practice import request as investigation_request

from pramana_contracts import QuietHours
from pramana_core import ids
from pramana_core.mail import FakeMailer
from pramana_core.questioning import decide_availability, in_quiet_hours

pytestmark = pytest.mark.db


def post(client: TestClient, path: str, body: Any = None, key: str | None = None) -> Any:
    return client.post(
        path, json=body, headers={**CSRF, "Idempotency-Key": key or uuid.uuid4().hex}
    )


def people_root(workspace: dict[str, Any]) -> str:
    return (
        f"/v1/orgs/{workspace['organization']['slug']}/sites/{workspace['live_site']['id']}/people"
    )


def patch_person(client: TestClient, root: str, body: dict[str, Any]) -> Any:
    return client.patch(
        root + "/p_ravi",
        json=body,
        headers={**CSRF, "Idempotency-Key": uuid.uuid4().hex, "If-Match": '"1"'},
    )


def synthetic_live(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise the live gate with the in-process simulator and synthetic people only."""
    models = client.app.state.investigations.site_models
    original = models.pin

    async def pin(site_id: uuid.UUID, *, practice: bool = False) -> Any:
        return await original(site_id, practice=True)

    monkeypatch.setattr(models, "pin", pin)
    monkeypatch.setattr(
        "pramana_core.investigations._now", lambda: datetime(2026, 11, 9, 12, tzinfo=UTC)
    )


def start_live(client: TestClient, workspace: dict[str, Any], root: str) -> dict[str, Any]:
    body = investigation_request(workspace["live_site"]["id"], "VALVE_F2.closed")
    response = post(client, root, body)
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    assert result["practice"] is False
    return result


def test_quiet_hours_respect_local_time_and_boundaries() -> None:
    window = QuietHours()
    assert in_quiet_hours(window, datetime(2026, 6, 1, 16, 30, tzinfo=UTC))
    assert in_quiet_hours(window, datetime(2026, 6, 2, 2, 29, tzinfo=UTC))
    assert not in_quiet_hours(window, datetime(2026, 6, 2, 2, 30, tzinfo=UTC))
    assert not in_quiet_hours(window.model_copy(update={"enabled": False}), datetime.now(UTC))
    no_consent = decide_availability(
        listed_available=True,
        has_web_contact_consent=False,
        quiet_hours=window,
        at=datetime(2026, 6, 1, 16, 30, tzinfo=UTC),
        quiet_hours_overridden=True,
    )
    assert not no_consent.available
    assert no_consent.reason == "no_consent"


def test_consent_link_is_single_use_expiring_and_tenant_bound(
    account_core: TestClient, migrated_db: str
) -> None:
    client = account_core
    workspace, _ = published_water_site(client)
    root = people_root(workspace)
    changed = patch_person(client, root, {"contact_email": "synthetic@example.test"})
    assert changed.status_code == 200, changed.text
    mailer = FakeMailer()
    client.app.state.mailer = mailer
    client.app.state.settings = client.app.state.settings.model_copy(
        update={
            "gmail_address": "sender@example.test",
            "gmail_app_password": SecretStr("fake"),
            "public_web_url": "https://pramana.example",
        }
    )
    request_path = root + "/p_ravi/consent-requests"
    key = uuid.uuid4().hex
    created = post(client, request_path, key=key)
    assert created.status_code == 201, created.text
    again = post(client, request_path, key=key)
    assert again.json() == created.json()
    assert again.headers["idempotent-replayed"] == "true"
    assert created.json()["email_delivery"] == "sent"
    assert len(mailer.sent) == 1
    assert mailer.sent[0][0] == "synthetic@example.test"
    assert "https://pramana.example" + created.json()["link_path"] in mailer.sent[0][2]

    code = created.json()["link_path"].removeprefix("/consent/")
    _, secret = code.split(".", 1)
    rows = sql(migrated_db, "select token_hash from consent_links")
    assert bytes(rows[0]["token_hash"]) == hashlib.sha256(secret.encode()).digest()
    public = "/v1/consent-links/" + code
    first = client.get(public)
    assert first.status_code == client.get(public).status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert first.json()["language"] == "hi"
    wrong = ids.encode("org", uuid.uuid4()) + "." + secret
    assert client.get("/v1/consent-links/" + wrong).status_code == 410
    granted = client.post(public, json={"decision": "granted"})
    assert granted.status_code == 200, granted.text
    assert client.post(public, json={"decision": "refused"}).status_code == 410
    assert client.get(public).status_code == 410

    refused_link = post(client, request_path).json()["link_path"].removeprefix("/consent/")
    refused = client.post("/v1/consent-links/" + refused_link, json={"decision": "refused"})
    assert refused.status_code == 200, refused.text
    records = client.get(root + "/p_ravi/consents").json()
    assert records[0]["decision"] == "refused"
    assert records[1]["decision"] == "granted"
    assert records[1]["withdrawn_at"] is not None

    expired = post(client, request_path).json()["link_path"].removeprefix("/consent/")
    expired_secret = expired.split(".", 1)[1]
    sql(
        migrated_db,
        "update consent_links set created_at=now()-interval '2 days', "
        "expires_at=now()-interval '1 day' where token_hash=:hash",
        {"hash": hashlib.sha256(expired_secret.encode()).digest()},
    )
    assert client.get("/v1/consent-links/" + expired).status_code == 410
    assert (
        client.post("/v1/consent-links/" + expired, json={"decision": "granted"}).status_code == 410
    )


def test_no_consent_then_withdrawal_cancels_question_and_replays(
    account_core: TestClient, monkeypatch: pytest.MonkeyPatch, migrated_db: str
) -> None:
    client = account_core
    workspace, investigations = published_water_site(client)
    synthetic_live(client, monkeypatch)
    initial = start_live(client, workspace, investigations)
    path = f"{investigations}/{initial['id']}"
    assert initial["status"] == "investigating"
    assert initial["pending_questions"] == []
    assert initial["questioning_availability"]["no_consent_count"] == 4

    people = people_root(workspace)
    link = post(client, people + "/p_ravi/consent-requests").json()["link_path"]
    response = client.post(
        "/v1/consent-links/" + link.removeprefix("/consent/"),
        json={"decision": "granted"},
    )
    assert response.status_code == 200, response.text
    state = client.get(path).json()
    assert state["questioning_availability"]["eligible_count"] == 1
    assert {q["action"]["participant_id"] for q in state["pending_questions"]} == {"p_ravi"}
    assert client.get(path + "/replay").json()["identical"] is True

    withdrawn = post(client, people + "/p_ravi/consents/contact_for_investigations/withdraw")
    assert withdrawn.status_code == 204, withdrawn.text
    after = client.get(path).json()
    assert after["pending_questions"] == []
    assert after["questioning_availability"]["no_consent_count"] == 4
    rows = sql(
        migrated_db,
        "select status from questions where investigation_id=:id",
        {"id": initial["id"]},
    )
    assert rows
    assert all(row["status"] == "cancelled" for row in rows)
    client.app.state.investigations._cache.clear()
    replay = client.get(path + "/replay").json()
    assert replay["identical"] is True
    assert replay["log_sealed"] is False
    events = client.get(path + "/events").json()
    assert any(e["type"] == "QuestionCancelled" for e in events)
    assert "synthetic@example.test" not in json.dumps(events)


def test_failed_replanning_does_not_consume_the_consent_link(
    account_core: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = account_core
    workspace, _ = published_water_site(client)
    root = people_root(workspace)
    link = post(client, root + "/p_ravi/consent-requests").json()["link_path"]
    public = "/v1/consent-links/" + link.removeprefix("/consent/")

    async def fail_replanning(*args: Any) -> None:
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(client.app.state.investigations, "consent_state_changed", fail_replanning)
    assert client.post(public, json={"decision": "granted"}).status_code == 500
    assert client.get(public).status_code == 200
    assert client.get(root + "/p_ravi/consents").json() == []


def test_quiet_hours_override_is_audited_and_replays(
    account_core: TestClient, monkeypatch: pytest.MonkeyPatch, migrated_db: str
) -> None:
    client = account_core
    workspace, investigations = published_water_site(client)
    people = people_root(workspace)
    changed = patch_person(
        client,
        people,
        {"quiet_hours": {"enabled": True, "start": "00:00", "end": "23:59", "timezone": "UTC"}},
    )
    assert changed.status_code == 200, changed.text
    granted = post(
        client,
        people + "/p_ravi/consents",
        {
            "purpose": "contact_for_investigations",
            "notice_version": "1",
            "language": "hi",
            "channel": "web",
            "evidence": {},
        },
    )
    assert granted.status_code == 201, granted.text
    synthetic_live(client, monkeypatch)
    state = start_live(client, workspace, investigations)
    path = f"{investigations}/{state['id']}"
    assert state["pending_questions"] == []
    assert state["questioning_availability"]["quiet_hours_count"] == 1
    assert post(client, path + "/availability/recheck").status_code == 200
    override = post(client, path + "/quiet-hours/override", {"reason": "Urgent water leak"})
    assert override.status_code == 200, override.text
    result = override.json()
    assert result["quiet_hours_override"]["reason"] == "Urgent water leak"
    assert {q["action"]["participant_id"] for q in result["pending_questions"]} == {"p_ravi"}
    assert (
        post(client, path + "/quiet-hours/override", {"reason": "Another emergency"}).status_code
        == 409
    )
    audit = sql(
        migrated_db,
        "select details from audit_log where action='quiet_hours.override' and target_id=:id",
        {"id": state["id"]},
    )
    assert len(audit) == 1
    assert audit[0]["details"]["reason"] == "Urgent water leak"
    client.app.state.investigations._cache.clear()
    replay = client.get(path + "/replay").json()
    assert replay["identical"] is True
    assert replay["log_sealed"] is False
