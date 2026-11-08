"""Names are sealed per person, consent is recorded, and erasure cannot be undone."""

from __future__ import annotations

import base64
import uuid
from typing import Any

import pytest
from auth_testkit import CSRF, login
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
from participant_bot import run_to_conclusion
from test_accounts import account_core as account_core
from test_accounts import create
from test_google_auth import sql
from test_practice import published_water_site
from test_practice import request as practice_request

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

    saved = sql(migrated_db, "select response_body from idempotency_keys")
    assert not [r for r in saved if r["response_body"] and NAME.encode() in r["response_body"]]

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


def test_erasing_a_person_keeps_the_replay_identical(
    account_core: TestClient, migrated_db: str
) -> None:
    """LC-03: nothing identifying is in the log, and erasure leaves the replay byte-identical."""
    client = account_core
    workspace, investigations = published_water_site(client)
    org = workspace["organization"]["slug"]
    site = workspace["live_site"]["id"]
    name, words = "Asha", "Doosre floor pe paani nahi aa raha"
    created = post(
        client, investigations, practice_request(site, "VALVE_F2.closed", practice=True)
    ).json()
    inv = created["id"]
    assert created["report"]["text"] == words
    assert name in [p["display_name"] for p in created["participants"]]

    class Scoped:
        def post(self, path: str, **kw: Any) -> Any:
            return client.post(
                path.replace("/v1/investigations", investigations),
                headers={**CSRF, "Idempotency-Key": uuid.uuid4().hex, **kw.pop("headers", {})},
                **kw,
            )

        def get(self, path: str, **kw: Any) -> Any:
            return client.get(path.replace("/v1/investigations", investigations), **kw)

    with TestClient(client.app.state.sim._http._transport.app) as sim:
        final, _ = run_to_conclusion(Scoped(), sim, created)  # type: ignore[arg-type]
    state_path = f"{investigations}/{inv}"
    assert post(client, f"{state_path}/reveal").status_code == 200
    before = client.get(f"{state_path}/replay").json()
    assert before["identical"] is True
    assert before["log_intact"] is True
    answered = [o for o in final["observations"] if o["transcript"]]
    assert answered, "the operator still reads what people said"

    rows = sql(
        migrated_db,
        "select type, payload::text as payload from events where investigation_id = :inv",
        {"inv": inv},
    )
    for row in rows:
        assert words not in row["payload"], row["type"]
        assert f'"display_name": "{name}"' not in row["payload"], row["type"]
    stored = sql(
        migrated_db,
        "select transcript from observations "
        "where investigation_id = :inv and transcript is not null",
        {"inv": inv},
    )
    assert stored == []

    assert post(client, f"/v1/orgs/{org}/sites/{site}/people/p_asha/erase").status_code == 204
    after = client.get(state_path).json()
    who = {p["id"]: p["display_name"] for p in after["participants"]}
    assert who["p_asha"] == "Erased person"
    assert who["p_guard"] == "Guard"
    assert after["report"]["text"] != words
    saved = sql(migrated_db, "select response_body from idempotency_keys")
    assert not [r for r in saved if r["response_body"] and words.encode() in r["response_body"]]
    for observation in after["observations"]:
        if observation["participant_id"] == "p_asha":
            assert observation["transcript"] is None

    replay = client.get(f"{state_path}/replay").json()
    assert replay["identical"] is True
    assert replay["log_intact"] is True
    assert replay["replayed_sha256"] == before["replayed_sha256"]
