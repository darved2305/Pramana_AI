"""Names are sealed per person, consent is recorded, and erasure cannot be undone."""

from __future__ import annotations

import base64
import uuid
from typing import Any

import pytest
from auth_testkit import CSRF, login
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
from test_accounts import account_core as account_core
from test_accounts import create
from test_google_auth import sql

from pramana_core.vault import MasterKey, PersonRef, PersonVault

pytestmark = pytest.mark.db

NAME = "Ananya Unique-Marker"
PERSON = {
    "id": "ananya",
    "display_name": NAME,
    "roles": ["staff"],
    "skill": "lay",
    "location_id": "LOBBY",
    "languages": {"stt_candidates": ["hi-IN", "en-IN"], "template_language": "hi"},
}


def post(client: TestClient, path: str, json: Any = None) -> Any:
    return client.post(path, json=json, headers={**CSRF, "Idempotency-Key": uuid.uuid4().hex})


def workspace(client: TestClient) -> tuple[str, str, str]:
    """A workspace whose live site has a draft model, so people can be placed."""
    created = create(client).json()
    org, site = created["organization"]["slug"], created["live_site"]["id"]
    draft = post(client, f"/v1/orgs/{org}/sites/{site}/draft", {"template_id": "office_water"})
    assert draft.status_code == 200, draft.text
    return org, created["organization"]["id"], site


def add_person(client: TestClient, org: str, site: str) -> dict[str, Any]:
    r = post(client, f"/v1/orgs/{org}/sites/{site}/people", PERSON)
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


def test_a_name_is_stored_only_sealed(account_core: TestClient, migrated_db: str) -> None:
    client = account_core
    org, _, site = workspace(client)
    added = add_person(client, org, site)
    assert added["person"]["display_name"] == NAME

    stored = sql(
        migrated_db,
        "select spec::text as spec, display_name_enc from site_people where id = 'ananya'",
    )
    assert NAME not in stored[0]["spec"]
    assert NAME.encode() not in bytes(stored[0]["display_name_enc"])

    listed = client.get(f"/v1/orgs/{org}/sites/{site}/people").json()
    assert [p["person"]["display_name"] for p in listed] == [NAME]

    patched = client.patch(
        f"/v1/orgs/{org}/sites/{site}/people/ananya",
        json={"question_budget": 2},
        headers={**CSRF, "Idempotency-Key": uuid.uuid4().hex, "If-Match": '"1"'},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["person"]["display_name"] == NAME
    assert patched.json()["person"]["question_budget"] == 2


def test_erasure_is_permanent_and_blocks_reuse(account_core: TestClient, migrated_db: str) -> None:
    client = account_core
    org, _, site = workspace(client)
    add_person(client, org, site)

    assert post(client, f"/v1/orgs/{org}/sites/{site}/people/ananya/erase").status_code == 204
    assert client.get(f"/v1/orgs/{org}/sites/{site}/people").json() == []
    key = sql(
        migrated_db, "select wrapped_key, erased_at from person_keys where person_id = 'ananya'"
    )
    assert key[0]["wrapped_key"] is None
    assert key[0]["erased_at"] is not None
    action = sql(
        migrated_db, "select details::text as details from audit_log where action = 'person.erased'"
    )
    assert len(action) == 1
    assert NAME not in action[0]["details"]

    # Erasing twice is harmless, and the id cannot quietly come back.
    assert post(client, f"/v1/orgs/{org}/sites/{site}/people/ananya/erase").status_code == 204
    again = post(client, f"/v1/orgs/{org}/sites/{site}/people", PERSON)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "PERSON_ERASED"


def test_only_owners_and_admins_can_erase(account_core: TestClient) -> None:
    client = account_core
    org, _, site = workspace(client)
    add_person(client, org, site)
    login(client, "approver")
    assert post(client, f"/v1/orgs/{org}/sites/{site}/people/ananya/erase").status_code in {
        403,
        404,
    }


def test_consent_is_recorded_replaced_and_withdrawn(account_core: TestClient) -> None:
    client = account_core
    org, _, site = workspace(client)
    add_person(client, org, site)
    base = f"/v1/orgs/{org}/sites/{site}/people/ananya/consents"
    grant = {
        "purpose": "voice_processing",
        "notice_version": "2026-11",
        "language": "hi-IN",
        "channel": "paper",
        "evidence": {"form": "A12"},
    }
    assert post(client, base, grant).status_code == 201
    assert post(client, base, {**grant, "notice_version": "2026-12"}).status_code == 201
    records = client.get(base).json()
    assert [r["notice_version"] for r in records] == ["2026-12", "2026-11"]
    assert records[0]["withdrawn_at"] is None
    assert records[1]["withdrawn_at"] is not None

    assert post(client, f"{base}/voice_processing/withdraw").status_code == 204
    assert all(r["withdrawn_at"] is not None for r in client.get(base).json())

    # The proof of consent outlives the person's name.
    assert post(client, f"/v1/orgs/{org}/sites/{site}/people/ananya/erase").status_code == 204
    assert len(client.get(base).json()) == 2


def test_a_ciphertext_cannot_be_moved_to_another_person() -> None:
    a = PersonRef(uuid.uuid4(), uuid.uuid4(), "a")
    b = PersonRef(a.org_id, a.site_id, "b")
    key = bytes(32)
    blob = PersonVault.encrypt(key, a, "display_name", "secret")
    assert PersonVault.decrypt(key, a, "display_name", blob) == "secret"
    with pytest.raises(InvalidTag):
        PersonVault.decrypt(key, b, "display_name", blob)
    master = MasterKey(bytes(range(32)))
    wrapped = master.wrap(key, a)
    assert master.unwrap(wrapped, a) == key
    with pytest.raises(InvalidTag):
        master.unwrap(wrapped, b)


def test_the_master_key_must_be_the_right_length() -> None:
    with pytest.raises(ValueError, match="32 bytes"):
        MasterKey(base64.urlsafe_b64decode("AAAA"))
