"""Participant links carry organization, scenario, person and retry identity independently."""

from __future__ import annotations

from typing import Any

import pytest
from auth_testkit import CSRF
from fastapi.testclient import TestClient
from test_accounts import account_core as account_core
from test_accounts import create
from test_google_auth import sql
from test_site_investigations import TenantClient

from pramana_contracts.tokens import mint, private_key_from_b64, verify

pytestmark = pytest.mark.db


def token(client: TenantClient, investigation: dict[str, Any], participant: str = "p_riya") -> str:
    response = client.post(
        f"/v1/investigations/{investigation['id']}/participants/{participant}/token"
    )
    assert response.status_code == 200, response.text
    assert response.json()["org_id"] == client.workspace["organization"]["id"]
    return response.json()["token"]


def headers(value: str, *, key: str = "participant-answer-001") -> dict[str, str]:
    return {"Authorization": f"Bearer {value}", "Idempotency-Key": key}


def test_participant_sees_only_their_state_and_no_staff_endpoints(account_core: TestClient) -> None:
    raw = account_core
    client = TenantClient(raw, create(raw).json())
    inv = client.start()
    bearer = token(client, inv)
    claims = verify(raw.app.state.participant_public_key, bearer)
    assert claims.org == client.workspace["organization"]["id"]
    raw.cookies.clear()
    root = client.root + "/" + inv["id"]
    state = raw.get(root, headers=headers(bearer))
    assert state.status_code == 200, state.text
    assert [p["id"] for p in state.json()["participants"]] == ["p_riya"]
    assert state.json()["belief"]["hypotheses"] == []
    assert state.json()["plan"]["candidates"] == []
    for path in (
        client.root,
        root + "/events",
        root + "/replay",
        client.root.removesuffix("/investigations") + "/sites",
    ):
        response = raw.get(path, headers=headers(bearer))
        assert response.status_code == 403, (path, response.text)
    assert raw.post(root + "/reveal", headers=headers(bearer)).status_code == 403


def test_token_cannot_cross_org_or_scenario_or_supply_legacy_missing_org(
    account_core: TestClient,
) -> None:
    raw = account_core
    a = TenantClient(raw, create(raw).json())
    first, second = a.start(), a.start()
    bearer = token(a, first)
    b = raw.post(
        "/v1/orgs",
        json={"name": "Other campus", "slug": "other-campus"},
        headers={**CSRF, "Idempotency-Key": "another-workspace-001"},
    ).json()
    claims = verify(raw.app.state.participant_public_key, bearer)
    signing = private_key_from_b64(
        raw.app.state.settings.participant_signing_key.get_secret_value()
    )
    raw.cookies.clear()
    assert raw.get(a.root + "/" + second["id"], headers=headers(bearer)).status_code == 404
    assert (
        raw.get(
            a.root.replace(a.workspace["organization"]["slug"], b["organization"]["slug"])
            + "/"
            + first["id"],
            headers=headers(bearer),
        ).status_code
        == 404
    )
    for org_id in (None, b["organization"]["id"], "org_invalid"):
        invalid_scope = mint(
            signing, participant_id=claims.sub, scenario_id=claims.scn, organization_id=org_id
        )
        response = raw.get(a.root + "/" + first["id"], headers=headers(invalid_scope))
        assert response.status_code == 404, response.text


def test_answer_replay_is_scoped_to_the_specific_participant_token(
    account_core: TestClient, migrated_db: str
) -> None:
    raw = account_core
    client = TenantClient(raw, create(raw).json())
    inv = client.start()
    token_a, token_b = token(client, inv), token(client, inv)
    q = inv["pending_question"]
    assert q["action"]["participant_id"] == "p_riya"
    payload = {"question_id": q["id"], "participant_id": "p_riya", "outcome": "no_network"}
    root = client.root + "/" + inv["id"] + "/answers"
    raw.cookies.clear()
    first = raw.post(root, json=payload, headers=headers(token_a))
    assert first.status_code == 200, first.text
    replay = raw.post(root, json=payload, headers=headers(token_a))
    assert replay.status_code == 200, replay.text
    assert replay.content == first.content
    assert replay.headers["idempotent-replayed"] == "true"
    assert replay.json()["state"]["belief"]["hypotheses"] == []
    other = raw.post(root, json=payload, headers=headers(token_b))
    assert "idempotent-replayed" not in other.headers
    assert other.status_code == 409, other.text
    principals = sql(
        migrated_db,
        "select principal from idempotency_keys where key=:key",
        {"key": "participant-answer-001"},
    )
    assert len(principals) == 2
    assert {row["principal"] for row in principals} == {
        "participant:" + verify(raw.app.state.participant_public_key, value).jti
        for value in (token_a, token_b)
    }


def test_another_participant_cannot_answer_the_witness_question(account_core: TestClient) -> None:
    raw = account_core
    client = TenantClient(raw, create(raw).json())
    inv = client.start()
    bearer = token(client, inv, "p_mahesh")
    raw.cookies.clear()
    response = raw.post(
        client.root + "/" + inv["id"] + "/answers",
        headers=headers(bearer),
        json={
            "question_id": inv["pending_question"]["id"],
            "participant_id": "p_riya",
            "outcome": "no_network",
        },
    )
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "PARTICIPANT_FORBIDDEN"
