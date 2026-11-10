"""Idempotency keys: every mutating route is protected, and concurrent retries have one effect."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from auth_testkit import CSRF
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from route_inventory import base_route, effective_path, registered_routes
from test_accounts import account_core as account_core
from test_accounts import create
from test_personal_data import PERSON

from pramana_core.idempotency import IdempotencyRoute

pytestmark = pytest.mark.db

MUTATING = frozenset({"POST", "PATCH", "PUT", "DELETE"})

LEGACY = (
    "legacy investigation/directory route, registered only outside production; the workspace "
    "route for the same handler is keyed"
)
# Mutating routes that deliberately do not use the idempotency-key wrapper. Each entry says why.
NOT_IDEMPOTENT: dict[tuple[str, str], str] = {
    ("POST", "/v1/investigations"): LEGACY,
    ("POST", "/v1/investigations/{inv_id}/participants/{participant_id}/token"): LEGACY,
    ("POST", "/v1/investigations/{inv_id}/interventions"): LEGACY,
    ("POST", "/v1/investigations/{inv_id}/approvals"): LEGACY,
    ("POST", "/v1/investigations/{inv_id}/approvals/{approval_id}/capability"): LEGACY,
    ("POST", "/v1/investigations/{inv_id}/approvals/{approval_id}/decision"): LEGACY,
    ("POST", "/v1/investigations/{inv_id}/reveal"): LEGACY,
    ("POST", "/v1/investigations/{inv_id}/answers"): LEGACY,
    ("POST", "/v1/investigations/{inv_id}/answers/voice"): LEGACY,
    ("POST", "/v1/participants"): LEGACY,
    ("PATCH", "/v1/participants/{participant_id}"): LEGACY,
    ("DELETE", "/v1/participants/{participant_id}"): LEGACY,
    ("POST", "/v1/voice/stt"): (
        "stateless speech-to-text: stores nothing in the workspace and returns the transcript"
    ),
    ("POST", "/v1/voice/tts"): (
        "stateless text-to-speech: stores nothing in the workspace; synthesis is cached by text"
    ),
    ("POST", "/v1/consent-links/{code}"): (
        "public one-time link: the link code is consumed on first use (consumed_at) and any "
        "repeat is refused with 410 CONSENT_LINK_INVALID, so the code, not a key, is the guard"
    ),
    ("POST", "/v1/auth/login"): (
        "credential exchange: each successful sign-in creates a new session by design; "
        "CSRF header and rate limits apply"
    ),
    ("POST", "/v1/auth/logout"): "ends the caller's session; a repeat has no further effect",
    ("POST", "/v1/auth/devices/revoke-others"): (
        "revokes the caller's other sessions; a repeat leaves the same revoked state"
    ),
    ("DELETE", "/v1/auth/devices/{device_id}"): (
        "revokes one device session; a repeat leaves the same revoked state"
    ),
}


def _mutating_routes(client: TestClient) -> list[tuple[str, str, APIRoute]]:
    found = []
    for route in registered_routes(client.app):
        base = base_route(route)
        if isinstance(base, APIRoute):
            for method in sorted(base.methods & MUTATING):
                found.append((method, effective_path(route), base))
    return found


def test_every_mutating_route_is_idempotent_or_explicitly_exempt(
    account_core: TestClient,
) -> None:
    routes = _mutating_routes(account_core)
    assert len(routes) >= 40
    unprotected: list[tuple[str, str]] = []
    unwrapped: list[tuple[str, str]] = []
    for method, path, route in routes:
        if (method, path) in NOT_IDEMPOTENT:
            continue
        if route.endpoint.__dict__.get("pramana_mutation") is not None:
            # The decorator alone is inert; the route class is what enforces the key.
            if not isinstance(route, IdempotencyRoute):
                unwrapped.append((method, path))
        else:
            unprotected.append((method, path))
    assert unwrapped == [], unwrapped
    assert unprotected == [], unprotected
    stale = sorted(set(NOT_IDEMPOTENT) - {(m, p) for m, p, _ in routes})
    assert stale == [], stale


def _race(sends: list[Callable[[], Any]]) -> list[Any]:
    """Fire every request at the same moment so they overlap inside the server."""
    barrier = threading.Barrier(len(sends))

    def run(send: Callable[[], Any]) -> Any:
        barrier.wait(10)
        return send()

    with ThreadPoolExecutor(max_workers=len(sends)) as pool:
        futures = [pool.submit(run, send) for send in sends]
        return [future.result(timeout=60) for future in futures]


def _workspace(client: TestClient) -> tuple[str, str]:
    created = create(client).json()
    return created["organization"]["slug"], created["live_site"]["id"]


def _invite_body(email: str) -> dict[str, Any]:
    return {"email": email, "roles": ["operator"]}


def _invitation_count(client: TestClient, org: str, email: str) -> int:
    items = client.get(f"/v1/orgs/{org}/invitations").json()["items"]
    return sum(1 for item in items if item["email"] == email)


def test_concurrent_invitations_with_one_key_create_one_invitation(
    account_core: TestClient,
) -> None:
    client = account_core
    org, _site = _workspace(client)
    email = f"race-{uuid.uuid4().hex[:8]}@example.invalid"
    key = uuid.uuid4().hex
    body = _invite_body(email)

    responses = _race(
        [
            lambda: client.post(
                f"/v1/orgs/{org}/invitations", json=body, headers={**CSRF, "Idempotency-Key": key}
            )
            for _ in range(6)
        ]
    )

    statuses = {r.status_code for r in responses}
    assert statuses <= {201, 409}, [(r.status_code, r.text) for r in responses]
    created = [r for r in responses if r.status_code == 201]
    assert created, "one request must complete"
    assert len({r.content for r in created}) == 1, "every completed attempt returns one body"
    assert {r.json()["error"]["code"] for r in responses if r.status_code == 409} <= {
        "IDEMPOTENCY_IN_FLIGHT"
    }
    assert _invitation_count(client, org, email) == 1


def test_concurrent_invitations_with_changed_bodies_create_one_effect(
    account_core: TestClient,
) -> None:
    client = account_core
    org, _site = _workspace(client)
    key = uuid.uuid4().hex
    emails = [f"changed-{i}-{uuid.uuid4().hex[:6]}@example.invalid" for i in range(4)]

    responses = _race(
        [
            lambda e=e: client.post(
                f"/v1/orgs/{org}/invitations",
                json=_invite_body(e),
                headers={**CSRF, "Idempotency-Key": key},
            )
            for e in emails
        ]
    )

    assert {r.status_code for r in responses} <= {201, 409, 422}, [
        (r.status_code, r.text) for r in responses
    ]
    assert sum(r.status_code == 201 for r in responses) == 1
    for response in responses:
        if response.status_code >= 400:
            assert response.json()["error"]["code"] in {
                "IDEMPOTENCY_KEY_REUSED",
                "IDEMPOTENCY_IN_FLIGHT",
            }, response.text
    assert sum(_invitation_count(client, org, e) for e in emails) == 1


def _people(client: TestClient, org: str, site: str) -> list[dict[str, Any]]:
    response = client.get(f"/v1/orgs/{org}/sites/{site}/people")
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def test_concurrent_person_creates_with_one_key_add_one_person(
    account_core: TestClient,
) -> None:
    client = account_core
    org, site = _workspace(client)
    draft = client.post(
        f"/v1/orgs/{org}/sites/{site}/draft",
        json={"template_id": "office_water"},
        headers={**CSRF, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert draft.status_code == 200, draft.text
    before = len(_people(client, org, site))
    key = uuid.uuid4().hex

    responses = _race(
        [
            lambda: client.post(
                f"/v1/orgs/{org}/sites/{site}/people",
                json=PERSON,
                headers={**CSRF, "Idempotency-Key": key},
            )
            for _ in range(5)
        ]
    )

    assert {r.status_code for r in responses} <= {201, 409}, [
        (r.status_code, r.text) for r in responses
    ]
    assert any(r.status_code == 201 for r in responses)
    assert len(_people(client, org, site)) == before + 1
