"""Route-derived actor matrix for the registered Core HTTP boundary."""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from auth_testkit import AUTO, CSRF, PASSWORD, USERS, login
from core_testkit import SIGNING_KEY, body
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from route_inventory import base_route as _base_route
from route_inventory import effective_path as _effective_path
from route_inventory import registered_routes as _registered_routes
from starlette.routing import WebSocketRoute
from test_accounts import create
from test_auth import secure_core as secure_core
from test_google_auth import sql as _sql

from pramana_contracts import StaffRole
from pramana_contracts.tokens import mint, private_key_from_b64
from pramana_core import ids
from pramana_core.idempotency import MutationPolicy
from pramana_core.tenant_routes import OrganizationRoute

pytestmark = pytest.mark.db

READ_ROLE_MATRIX = {
    ("GET", "/v1/orgs/{org}/export"): frozenset({"owner"}),
    (
        "GET",
        "/v1/orgs/{org}/sites/{site_id}/people/{person_id}/consent-requests/{request_id}",
    ): frozenset({"operator", "owner", "admin"}),
    (
        "GET",
        "/v1/orgs/{org}/investigations/{inv_id}/questions/{question_id}/audio",
    ): frozenset({"owner", "admin", "operator", "viewer"}),
    ("GET", "/v1/orgs/{org}/domains"): frozenset({"owner", "admin"}),
    ("GET", "/v1/orgs/{org}/join-requests"): frozenset({"owner", "admin"}),
}
READ_DENIAL_CODE_MATRIX = {
    ("GET", "/v1/orgs/{org}/export"): "OWNER_ONLY",
}

MATRIX_ACTORS = frozenset(
    {
        "anonymous",
        "participant",
        "owner",
        "admin",
        "operator",
        "approver",
        "viewer",
        "global_operator",
        "global_approver",
        "org_b_member",
        "simulator_operator",
    }
)
USER_ACTORS = frozenset(MATRIX_ACTORS - {"anonymous", "participant", "simulator_operator"})
OPERATOR_ACTORS = frozenset(
    {
        "owner",
        "admin",
        "operator",
        "viewer",
        "global_operator",
        "org_b_member",
    }
)
APPROVER_ACTORS = frozenset({"operator", "approver", "global_approver"})
STAFF_ACTORS = OPERATOR_ACTORS | APPROVER_ACTORS
READ_INVESTIGATION_ACTORS = USER_ACTORS | {"participant"}
OPERATOR_OR_PARTICIPANT_ACTORS = OPERATOR_ACTORS | {"participant"}

# Every non-tenant HTTP route is listed here. Values are callers admitted by the route's
# authentication/role boundary; endpoint and object checks may still reject them.
CORE_HTTP_ROLE_MATRIX = {
    ("GET", "/health"): MATRIX_ACTORS,
    ("GET", "/ready"): MATRIX_ACTORS,
    ("POST", "/v1/auth/login"): MATRIX_ACTORS,
    ("POST", "/v1/auth/logout"): MATRIX_ACTORS,
    ("GET", "/v1/auth/session"): USER_ACTORS,
    ("GET", "/v1/auth/google/start"): MATRIX_ACTORS,
    ("GET", "/v1/auth/google/callback"): MATRIX_ACTORS,
    ("GET", "/v1/auth/devices"): USER_ACTORS,
    ("POST", "/v1/auth/devices/revoke-others"): USER_ACTORS,
    ("DELETE", "/v1/auth/devices/{device_id}"): USER_ACTORS,
    ("GET", "/v1/me"): USER_ACTORS,
    ("PATCH", "/v1/me/preferences"): USER_ACTORS,
    ("GET", "/v1/onboarding"): USER_ACTORS,
    ("PATCH", "/v1/onboarding"): USER_ACTORS,
    ("POST", "/v1/orgs"): USER_ACTORS,
    ("POST", "/v1/join-requests"): USER_ACTORS,
    ("POST", "/v1/join-requests/{request_id}/cancel"): USER_ACTORS,
    ("GET", "/v1/library/equipment"): USER_ACTORS,
    ("GET", "/v1/library/templates"): USER_ACTORS,
    ("GET", "/v1/consent-links/{code}"): MATRIX_ACTORS,
    ("POST", "/v1/consent-links/{code}"): MATRIX_ACTORS,
    ("POST", "/v1/invitations/accept"): USER_ACTORS,
    ("POST", "/v1/invitations/accept-pending"): USER_ACTORS,
    ("GET", "/v1/investigations"): STAFF_ACTORS,
    ("POST", "/v1/investigations"): OPERATOR_ACTORS,
    ("GET", "/v1/investigations/{inv_id}"): READ_INVESTIGATION_ACTORS,
    ("POST", "/v1/investigations/{inv_id}/answers"): OPERATOR_OR_PARTICIPANT_ACTORS,
    ("POST", "/v1/investigations/{inv_id}/reveal"): OPERATOR_ACTORS,
    ("GET", "/v1/investigations/{inv_id}/forecast"): STAFF_ACTORS,
    ("GET", "/v1/investigations/{inv_id}/map-drift"): STAFF_ACTORS,
    ("GET", "/v1/investigations/{inv_id}/events"): STAFF_ACTORS,
    ("POST", "/v1/investigations/{inv_id}/approvals"): OPERATOR_ACTORS,
    (
        "POST",
        "/v1/investigations/{inv_id}/approvals/{approval_id}/decision",
    ): APPROVER_ACTORS,
    (
        "POST",
        "/v1/investigations/{inv_id}/approvals/{approval_id}/capability",
    ): OPERATOR_OR_PARTICIPANT_ACTORS,
    ("POST", "/v1/investigations/{inv_id}/interventions"): OPERATOR_OR_PARTICIPANT_ACTORS,
    (
        "POST",
        "/v1/investigations/{inv_id}/participants/{participant_id}/token",
    ): OPERATOR_ACTORS,
    ("GET", "/v1/participants"): STAFF_ACTORS,
    ("POST", "/v1/participants"): OPERATOR_ACTORS,
    ("GET", "/v1/participants/{participant_id}"): STAFF_ACTORS,
    ("PATCH", "/v1/participants/{participant_id}"): OPERATOR_ACTORS,
    ("DELETE", "/v1/participants/{participant_id}"): OPERATOR_ACTORS,
    ("GET", "/v1/evaluation/reports"): STAFF_ACTORS,
    ("GET", "/v1/evaluation/reports/{run_id}"): STAFF_ACTORS,
    ("GET", "/v1/investigations/{inv_id}/stream"): STAFF_ACTORS,
    ("GET", "/v1/investigations/{inv_id}/replay"): STAFF_ACTORS,
    ("GET", "/v1/packs"): MATRIX_ACTORS,
    ("GET", "/v1/packs/{pack_id}"): MATRIX_ACTORS,
    ("GET", "/v1/voice/status"): STAFF_ACTORS,
    ("GET", "/v1/voice/usage"): STAFF_ACTORS,
    ("POST", "/v1/voice/stt"): OPERATOR_ACTORS,
    ("POST", "/v1/voice/tts"): OPERATOR_ACTORS,
    (
        "GET",
        "/v1/investigations/{inv_id}/questions/{question_id}/audio",
    ): OPERATOR_OR_PARTICIPANT_ACTORS,
    ("POST", "/v1/investigations/{inv_id}/answers/voice"): OPERATOR_OR_PARTICIPANT_ACTORS,
}

CORE_WEBSOCKET_ROLE_MATRIX = {
    ("WS", "/v1/voice/stream"): OPERATOR_ACTORS,
    (
        "WS",
        "/v1/investigations/{inv_id}/questions/{question_id}/media",
    ): frozenset({"participant"}),
    (
        "WS",
        "/v1/investigations/{inv_id}/participants/{participant_id}/call",
    ): frozenset({"participant"}),
    (
        "WS",
        "/v1/orgs/{org}/investigations/{inv_id}/questions/{question_id}/media",
    ): frozenset({"participant"}),
    (
        "WS",
        "/v1/orgs/{org}/investigations/{inv_id}/participants/{participant_id}/call",
    ): frozenset({"participant"}),
}


def sql(url: str, statement: str, **params: Any) -> list[dict[str, Any]]:
    return _sql(url, statement, params)


def _login_cookie(client: TestClient, email: str) -> str:
    client.cookies.clear()
    response = client.post(
        "/v1/auth/login",
        json={"email": email, "password": PASSWORD},
        headers=CSRF,
    )
    assert response.status_code == 200, response.text
    name = client.app.state.settings.session_cookie_name
    return f"{name}={response.cookies[name]}"


def _add_user(
    client: TestClient,
    email: str,
    display_name: str,
    roles: list[StaffRole] | None = None,
) -> str:
    assert client.portal is not None
    user = client.portal.call(
        client.app.state.auth.create_user,
        email,
        display_name,
        PASSWORD,
        roles or [StaffRole.OPERATOR],
    )
    return str(user.id)


def _member(migrated_db: str, org_id: str, user_id: str, role: str) -> None:
    sql(
        migrated_db,
        "insert into memberships (org_id, user_id, roles, status) "
        "values (:org, :user, ARRAY[:role]::text[], 'active') "
        "on conflict (org_id, user_id) do update set roles = excluded.roles, status = 'active'",
        org=org_id,
        user=user_id,
        role=role,
    )


def _concrete_path(template: str, values: dict[str, str]) -> str:
    names = set(re.findall(r"\{([a-z_]+)\}", template))
    assert names <= values.keys(), (template, names - values.keys())
    return re.sub(r"\{([a-z_]+)\}", lambda match: values[match.group(1)], template)


def _matrix_path(template: str, workspace: dict[str, Any], *, org: str | None = None) -> str:
    return _concrete_path(
        template,
        {
            "org": org or workspace["organization"]["slug"],
            "site_id": workspace["sandbox_site"]["id"],
            "model_id": workspace["sandbox_site"]["current_model_id"],
            "inv_id": ids.new("inv")[1],
            "question_id": "q_matrix_missing",
            "approval_id": str(uuid.uuid4()),
            "participant_id": "p_matrix",
            "member_id": "usr_matrix_missing",
            "person_id": "p_matrix_missing",
            "purpose": "voice_processing",
            "request_id": ids.new("join")[1],
            "domain": "matrix.invalid",
            "invite_id": ids.new("invite")[1],
            "device_id": "0" * 64,
            "run_id": "matrix_missing_run",
            "pack_id": "campus_block_c",
            "sid": "sid_matrix_missing",
            "code": "matrix-invalid-consent-code",
        },
    )


def _matrix_context(
    client: TestClient, migrated_db: str
) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, str]], dict[str, str]]:
    login(client, "operator")
    workspace_a = create(client, name="Matrix A", slug="matrix-a").json()
    org_a_id = str(ids.decode("org", workspace_a["organization"]["id"]))
    cookie_name = client.app.state.settings.session_cookie_name
    cookies: dict[str, str] = {"owner": f"{cookie_name}={client.cookies[cookie_name]}"}

    user_ids = client.user_ids  # type: ignore[attr-defined]
    admin_id = _add_user(client, "matrix-admin@pramana.test", "Matrix Admin")
    viewer_id = _add_user(client, "matrix-viewer@pramana.test", "Matrix Viewer")
    _add_user(client, "matrix-b@pramana.test", "Matrix B Member")
    _add_user(client, "matrix-global-operator@pramana.test", "Matrix Global Operator")
    _add_user(
        client,
        "matrix-global-approver@pramana.test",
        "Matrix Global Approver",
        [StaffRole.APPROVER],
    )

    _member(migrated_db, org_a_id, user_ids["operator"], "owner")
    _member(migrated_db, org_a_id, user_ids["approver"], "approver")
    _member(migrated_db, org_a_id, user_ids["both"], "operator")
    _member(migrated_db, org_a_id, admin_id, "admin")
    _member(migrated_db, org_a_id, viewer_id, "viewer")

    cookies["org_b_member"] = _login_cookie(client, "matrix-b@pramana.test")
    created_b = client.post(
        "/v1/orgs",
        json={"name": "Matrix B", "slug": "matrix-b"},
        headers={**CSRF, "Idempotency-Key": "matrix-workspace-b-0001"},
    )
    assert created_b.status_code == 201, created_b.text
    workspace_b = created_b.json()

    cookies["admin"] = _login_cookie(client, "matrix-admin@pramana.test")
    cookies["operator"] = _login_cookie(client, USERS["both"][0])
    cookies["approver"] = _login_cookie(client, USERS["approver"][0])
    cookies["viewer"] = _login_cookie(client, "matrix-viewer@pramana.test")
    cookies["global_operator"] = _login_cookie(client, "matrix-global-operator@pramana.test")
    cookies["global_approver"] = _login_cookie(client, "matrix-global-approver@pramana.test")
    client.cookies.clear()

    participant = mint(
        private_key_from_b64(SIGNING_KEY),
        participant_id="p_matrix",
        scenario_id="inv_matrix_missing",
        organization_id=workspace_a["organization"]["id"],
    )
    actor_headers = {
        "anonymous": {},
        "participant": {"Authorization": f"Bearer {participant}"},
        **{
            actor: {"Cookie": cookie}
            for actor, cookie in cookies.items()
            if actor != "org_b_member"
        },
        "org_b_member": {"Cookie": cookies["org_b_member"]},
        "simulator_operator": {"X-Operator-Key": "test-operator-key"},
    }
    actor_roles = {
        "owner": "owner",
        "admin": "admin",
        "operator": "operator",
        "approver": "approver",
        "viewer": "viewer",
    }
    return workspace_a, workspace_b, actor_headers, actor_roles


def test_every_registered_org_http_route_has_an_exercised_role_matrix(
    secure_core: TestClient, migrated_db: str
) -> None:
    client = secure_core
    workspace_a, workspace_b, actor_headers, actor_roles = _matrix_context(client, migrated_db)

    routes = [
        (route, method)
        for route in _registered_routes(client.app)
        if isinstance(_base_route(route), APIRoute) and route.path.startswith("/v1/orgs/{org}")
        for method in route.methods or ()
        if method in {"GET", "POST", "PATCH", "PUT", "DELETE"}
    ]
    assert len(routes) >= 58
    assert all(
        isinstance(_base_route(route), OrganizationRoute) or route.path == "/v1/orgs/{org}"
        for route, _ in routes
    )

    for route, method in routes:
        organization_boundary = isinstance(_base_route(route), OrganizationRoute)
        policy = route.endpoint.__dict__.get("pramana_mutation")
        if organization_boundary and (
            method not in {"GET", "HEAD", "OPTIONS"} or policy is not None
        ):
            assert isinstance(policy, MutationPolicy), (method, route.path)
        path = _matrix_path(route.path, workspace_a)
        participant_allowed = bool(route.endpoint.__dict__.get("pramana_participants", False))
        for actor, headers in actor_headers.items():
            request_headers = dict(headers)
            content = None
            if method not in {"GET", "HEAD", "OPTIONS"}:
                request_headers.update(
                    {
                        **CSRF,
                        "Idempotency-Key": "route-matrix-probe-0001",
                        "Content-Type": "application/json",
                    }
                )
                content = b"{"  # Invalid before handlers can mutate data.
            response = client.request(method, path, content=content, headers=request_headers)

            if actor in {"anonymous", "simulator_operator"}:
                assert response.status_code == 401, (method, route.path, actor, response.text)
            elif actor in {"org_b_member", "global_operator", "global_approver"}:
                assert response.status_code == 404, (method, route.path, actor, response.text)
            elif actor == "participant":
                if not organization_boundary:
                    assert response.status_code == 401, (
                        method,
                        route.path,
                        actor,
                        response.status_code,
                        response.text,
                    )
                elif participant_allowed:
                    assert response.status_code == 404, (
                        method,
                        route.path,
                        actor,
                        response.status_code,
                        response.text,
                    )
                else:
                    assert response.status_code == 403, (
                        method,
                        route.path,
                        actor,
                        response.status_code,
                        response.text,
                    )
            else:
                role = actor_roles[actor]
                allowed_roles = (
                    frozenset(policy.roles)
                    if isinstance(policy, MutationPolicy)
                    else READ_ROLE_MATRIX.get((method, route.path), frozenset(actor_roles))
                )
                denied = role not in allowed_roles
                if denied:
                    assert response.status_code in {403, 404}, (
                        method,
                        route.path,
                        actor,
                        response.status_code,
                        response.text,
                    )
                    expected_code = (
                        "NOT_FOUND"
                        if response.status_code == 404
                        else READ_DENIAL_CODE_MATRIX.get((method, route.path), "ROLE_FORBIDDEN")
                    )
                    assert response.json()["error"]["code"] == expected_code, (
                        method,
                        route.path,
                        actor,
                        response.json(),
                    )
                else:
                    assert response.status_code not in {401, 403}, (
                        method,
                        route.path,
                        actor,
                        response.status_code,
                        response.text,
                    )

            if response.status_code >= 400:
                assert set(response.json()) == {"error"}, (method, route.path, actor, response.text)
                assert {"code", "message", "request_id"} <= set(response.json()["error"])

    # An organization B member addressing A's actual site and model ids must not read them
    # through B's otherwise-valid membership boundary.
    for route, method in routes:
        if method != "GET" or not {"site_id", "model_id"}.intersection(
            re.findall(r"\{([a-z_]+)\}", route.path)
        ):
            continue
        path = _matrix_path(route.path, workspace_a, org=workspace_b["organization"]["slug"])
        for actor in ("org_b_member", "global_operator", "global_approver"):
            response = client.get(path, headers=actor_headers[actor])
            assert response.status_code == 404, (
                method,
                route.path,
                actor,
                response.status_code,
                response.text,
            )


def _core_probe_body(method: str, template: str, workspace_a: dict[str, Any]) -> dict[str, Any]:
    if method not in {"POST", "PATCH", "PUT", "DELETE"}:
        return {}
    if template == "/v1/orgs":
        return {"name": "Duplicate Matrix A", "slug": workspace_a["organization"]["slug"]}
    if template == "/v1/join-requests":
        return {"organization_id": ids.new("org")[1]}
    if template == "/v1/join-requests/{request_id}/cancel":
        return {}
    if template == "/v1/invitations/accept":
        return {"token": "x" * 20}
    if template == "/v1/invitations/accept-pending":
        return {"organization_id": "org_matrix_missing", "invitation_id": "inv_matrix_missing"}
    if template == "/v1/investigations/{inv_id}/answers":
        return {"question_id": "q_matrix_missing", "participant_id": "p_matrix", "text": "yes"}
    if template == "/v1/investigations/{inv_id}/interventions":
        return {"approval_id": str(uuid.uuid4()), "participant_id": "p_matrix"}
    if template == "/v1/investigations/{inv_id}/answers/voice":
        return {}
    return {}


def _read_socket_close(ws: Any) -> tuple[int | None, dict[str, Any] | None]:
    last_json: dict[str, Any] | None = None
    try:
        while True:
            message = ws.receive()
            if message["type"] in {"websocket.disconnect", "websocket.close"}:
                return int(message.get("code", 1000)), last_json
            raw = message.get("text")
            if raw:
                try:
                    import json

                    value = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(value, dict):
                    last_json = value
    except Exception as exc:
        code = getattr(exc, "code", None)
        return (int(code) if code is not None else None), last_json


def _socket_investigations(
    client: TestClient,
    workspace_a: dict[str, Any],
    actor_headers: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    legacy = client.post(
        "/v1/investigations",
        json=body(fault="CB_C2_7.tripped"),
        headers=AUTO,
    )
    assert legacy.status_code == 201, legacy.text
    legacy_state = legacy.json()
    legacy_participant = legacy_state["pending_question"]["action"]["participant_id"]
    legacy_token = client.post(
        f"/v1/investigations/{legacy_state['id']}/participants/{legacy_participant}/token",
        headers=AUTO,
    )
    assert legacy_token.status_code == 200, legacy_token.text

    organization = workspace_a["organization"]
    site_request = body(fault="CB_C2_7.tripped")
    site_request.pop("pack_id")
    site_request["site_id"] = workspace_a["sandbox_site"]["id"]
    tenant_path = f"/v1/orgs/{organization['slug']}/investigations"
    tenant = client.post(
        tenant_path,
        json=site_request,
        headers={
            **actor_headers["owner"],
            **CSRF,
            "Idempotency-Key": "socket-matrix-tenant-investigation-0001",
        },
    )
    assert tenant.status_code == 201, tenant.text
    tenant_state = tenant.json()
    tenant_participant = tenant_state["pending_question"]["action"]["participant_id"]
    tenant_token = client.post(
        f"{tenant_path}/{tenant_state['id']}/participants/{tenant_participant}/token",
        headers={
            **actor_headers["owner"],
            **CSRF,
            "Idempotency-Key": "socket-matrix-tenant-token-0001",
        },
    )
    assert tenant_token.status_code == 200, tenant_token.text

    return {
        "legacy": {
            "inv_id": legacy_state["id"],
            "question_id": legacy_state["pending_question"]["id"],
            "participant_id": legacy_participant,
            "token": legacy_token.json()["token"],
        },
        "tenant": {
            "org": organization["id"],
            "inv_id": tenant_state["id"],
            "question_id": tenant_state["pending_question"]["id"],
            "participant_id": tenant_participant,
            "token": tenant_token.json()["token"],
        },
    }


def test_every_registered_non_tenant_http_and_websocket_route_has_an_actor_matrix(
    secure_core: TestClient, migrated_db: str
) -> None:
    client = secure_core
    workspace_a, _workspace_b, actor_headers, _actor_roles = _matrix_context(client, migrated_db)

    http_routes = {
        (method, route.path)
        for route in _registered_routes(client.app)
        if isinstance(_base_route(route), APIRoute) and not route.path.startswith("/v1/orgs/{org}")
        for method in route.methods or ()
        if method in {"GET", "POST", "PATCH", "PUT", "DELETE"}
    }
    assert http_routes == set(CORE_HTTP_ROLE_MATRIX), {
        "missing_policy": sorted(http_routes - set(CORE_HTTP_ROLE_MATRIX)),
        "stale_policy": sorted(set(CORE_HTTP_ROLE_MATRIX) - http_routes),
    }

    for method, template in sorted(http_routes):
        path = _matrix_path(template, workspace_a)
        allowed_actors = CORE_HTTP_ROLE_MATRIX[(method, template)]
        for actor in MATRIX_ACTORS:
            headers = {**actor_headers[actor], **CSRF}
            if method in {"POST", "PATCH", "PUT", "DELETE"}:
                headers["Idempotency-Key"] = "non-tenant-route-matrix-0001"
                headers["If-Match"] = '"0"'
            if template == "/v1/auth/logout":
                headers = dict(CSRF)

            if template == "/v1/voice/stt":
                response = client.request(
                    method,
                    path,
                    data={"language_codes": "hi-IN,en-IN"},
                    files={"audio": ("empty.wav", b"")},
                    headers=headers,
                )
            elif template == "/v1/investigations/{inv_id}/answers/voice":
                response = client.request(
                    method,
                    path,
                    data={"question_id": "q_matrix_missing", "participant_id": "p_matrix"},
                    files={"audio": ("empty.wav", b"")},
                    headers=headers,
                )
            elif template == "/v1/investigations/{inv_id}/approvals/{approval_id}/capability":
                response = client.request(
                    method, path + "?participant_id=p_matrix", headers=headers
                )
            elif method in {"POST", "PATCH", "PUT", "DELETE"}:
                response = client.request(
                    method,
                    path,
                    json=_core_probe_body(method, template, workspace_a),
                    headers=headers,
                )
            else:
                response = client.request(method, path, headers=headers)

            if actor in allowed_actors:
                assert response.status_code not in {401, 403}, (
                    method,
                    template,
                    actor,
                    response.status_code,
                    response.text,
                )
            else:
                assert response.status_code in {401, 403}, (
                    method,
                    template,
                    actor,
                    response.status_code,
                    response.text,
                )
            if response.status_code >= 400:
                body = response.json()
                assert set(body) == {"error"}, (method, template, actor, body)
                assert {"code", "message", "request_id"} <= set(body["error"])

    websocket_routes = {
        ("WS", _effective_path(route))
        for route in _registered_routes(client.app)
        if isinstance(_base_route(route), WebSocketRoute)
    }
    assert websocket_routes == set(CORE_WEBSOCKET_ROLE_MATRIX), {
        "missing_policy": sorted(websocket_routes - set(CORE_WEBSOCKET_ROLE_MATRIX)),
        "stale_policy": sorted(set(CORE_WEBSOCKET_ROLE_MATRIX) - websocket_routes),
    }
    socket_cases = _socket_investigations(client, workspace_a, actor_headers)
    for _kind, template in sorted(websocket_routes):
        socket_case = socket_cases["tenant" if "/orgs/{org}/" in template else "legacy"]
        path = _concrete_path(template, socket_case) if "{" in template else template
        allowed_actors = CORE_WEBSOCKET_ROLE_MATRIX[("WS", template)]
        for actor in MATRIX_ACTORS:
            headers = dict(actor_headers[actor])
            if actor in allowed_actors:
                if template == "/v1/voice/stream":
                    with client.websocket_connect(path, headers=headers) as ws:
                        ws.send_json({"type": "stop"})
                        close_code, message = _read_socket_close(ws)
                    assert close_code == 1008 or (message or {}).get("type") == "error", (
                        template,
                        actor,
                        close_code,
                        message,
                    )
                    continue
                try:
                    with client.websocket_connect(path, headers=headers) as ws:
                        token = socket_case["token"]
                        ws.send_json({"type": "start", "token": token, "play": False})
                        if template.endswith("/call"):
                            assert ws.receive_json()["type"] == "ringing"
                            ws.send_json({"type": "decline"})
                            close_code, message = _read_socket_close(ws)
                            assert close_code == 1000, (template, actor, close_code, message)
                        else:
                            close_code, message = _read_socket_close(ws)
                            assert close_code == 4503 or (message or {}).get("type") == "error", (
                                template,
                                actor,
                                close_code,
                                message,
                            )
                except Exception as exc:
                    pytest.fail(f"{template} rejected authorized participant: {exc}")
            elif template == "/v1/voice/stream":
                with (
                    pytest.raises(Exception) as denied,
                    client.websocket_connect(path, headers=headers),
                ):
                    pass
                assert getattr(denied.value, "code", None) == 4401, (
                    template,
                    actor,
                    repr(denied.value),
                )
            else:
                with client.websocket_connect(path, headers=headers) as ws:
                    ws.send_json({"type": "start", "token": "", "play": False})
                    close_code, message = _read_socket_close(ws)
                assert close_code == 4401, (template, actor, close_code, message)
