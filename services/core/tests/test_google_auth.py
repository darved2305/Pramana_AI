"""Google identity and session boundaries, with a signed in-process mock issuer."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx
import pytest
from auth_testkit import CSRF, PASSWORD
from core_testkit import body, core_settings, truncate_all
from fastapi import FastAPI
from fastapi.testclient import TestClient
from joserfc.jwk import RSAKey
from live_server import read_sse, serve
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from pramana_contracts import StaffRole
from pramana_core.auth.service import AuthService, LoginThrottle
from pramana_core.db import Database
from pramana_core.main import create_app

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from mock_oidc import MockIssuer

pytestmark = pytest.mark.db


@pytest.fixture(params=["owner", "runtime"])
def oauth_core(
    request: pytest.FixtureRequest, migrated_db: str, sim_app: FastAPI
) -> Iterator[tuple[TestClient, MockIssuer]]:
    asyncio.run(truncate_all(migrated_db))
    fake = MockIssuer()
    app_url = migrated_db
    if request.param == "runtime":
        app_url = (
            make_url(migrated_db)
            .set(username="pramana_app", password=None)
            .render_as_string(hide_password=False)
        )
    cfg = core_settings(
        app_url,
        AUTH_REQUIRED=True,
        CORE_AUTOMATION_KEY="",
        OIDC_ISSUER=fake.issuer,
        OIDC_DISCOVERY_URL=f"{fake.issuer}/.well-known/openid-configuration",
        GOOGLE_OAUTH_CLIENT_ID=fake.client_id,
        GOOGLE_OAUTH_CLIENT_SECRET="local-only",
        OIDC_REDIRECT_URL="http://testserver/v1/auth/google/callback",
        LOGIN_MAX_FAILURES=3,
    )
    app = create_app(
        cfg,
        sim_transport=httpx.ASGITransport(app=sim_app),
        oidc_transport=httpx.MockTransport(fake.transport),
    )
    with TestClient(app) as client:
        yield client, fake


def sql(url: str, statement: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    async def run() -> list[dict[str, Any]]:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as conn:
                result = await conn.execute(text(statement), params or {})
                return [dict(r) for r in result.mappings()] if result.returns_rows else []
        finally:
            await engine.dispose()

    return asyncio.run(run())


def password_user(url: str, email: str = "local@gmail.com") -> str:
    async def run() -> str:
        db = Database(create_async_engine(url))
        try:
            user = await AuthService(db, 43200, LoginThrottle(3, 300)).create_user(
                email, "Existing account", PASSWORD, [StaffRole.OPERATOR]
            )
            return user.id
        finally:
            await db.dispose()

    return asyncio.run(run())


def start(client: TestClient, next_path: str = "/app") -> dict[str, str]:
    response = client.get(
        "/v1/auth/google/start", params={"next": next_path}, follow_redirects=False
    )
    assert response.status_code == 302, response.text
    assert response.headers["cache-control"] == "no-store"
    query = dict(parse_qsl(urlsplit(response.headers["location"]).query))
    assert query["scope"] == "openid email profile"
    assert query["code_challenge_method"] == "S256"
    assert len(query["state"]) >= 32
    assert len(query["nonce"]) >= 32
    return query


def finish(client: TestClient, fake: MockIssuer, query: dict[str, str]) -> httpx.Response:
    code = fake.issue_code(query)
    return client.get(
        "/v1/auth/google/callback",
        params={"state": query["state"], "code": code},
        follow_redirects=False,
    )


def test_id_01_new_gmail_identity_has_no_global_staff_roles(
    oauth_core: tuple[TestClient, MockIssuer],
) -> None:
    client, fake = oauth_core
    response = finish(client, fake, start(client))
    assert response.status_code == 302
    assert response.headers["location"] == "/app"
    me = client.get("/v1/auth/session").json()
    assert me["email"] == "local@gmail.com"
    assert me["email_verified"] is True
    assert me["roles"] == []
    assert client.post("/v1/investigations", json=body(), headers=CSRF).status_code == 403
    assert client.cookies.get("pramana_auth") is None


def test_id_02_workspace_hd_is_recorded(
    oauth_core: tuple[TestClient, MockIssuer], migrated_db: str
) -> None:
    client, fake = oauth_core
    fake.claims.update(email="staff@college.edu", hd="college.edu")
    assert finish(client, fake, start(client)).headers["location"] == "/app"
    assert (
        sql(migrated_db, "select hosted_domain from user_identities")[0]["hosted_domain"]
        == "college.edu"
    )
    assert client.get("/v1/auth/session").json()["email_verified"] is True


def test_custom_email_without_hd_needs_email_verification(
    oauth_core: tuple[TestClient, MockIssuer],
) -> None:
    client, fake = oauth_core
    fake.claims.update(email="staff@custom.example")
    finish(client, fake, start(client))
    assert client.get("/v1/auth/session").json()["email_verified"] is False


def test_workspace_alias_uses_verified_hd_claim(oauth_core: tuple[TestClient, MockIssuer]) -> None:
    client, fake = oauth_core
    fake.claims.update(email="staff@alias.edu", hd="college.edu")
    assert finish(client, fake, start(client)).headers["location"] == "/app"
    assert client.get("/v1/auth/session").json()["email_verified"] is True


@pytest.mark.parametrize(
    "overrides",
    [
        {"aud": "another-client"},
        {"aud": ["pramana-local", "other"]},
        {"azp": "other"},
        {"iss": "https://evil.example"},
        {"exp": 1},
        {"iat": 9999999999},
        {"nonce": "wrong"},
        {"sub": ""},
        {"sub": None},
        {"email_verified": "true"},
        {"hd": ["college.edu"]},
        {"email": "invalid"},
        {"exp": True},
    ],
)
def test_invalid_id_token_fails_closed(
    oauth_core: tuple[TestClient, MockIssuer], migrated_db: str, overrides: dict[str, Any]
) -> None:
    client, fake = oauth_core
    fake.overrides.update(overrides)
    response = finish(client, fake, start(client))
    assert response.headers["location"] == "/login?error=sign_in_failed"
    assert client.get("/v1/auth/session").status_code == 401
    assert sql(migrated_db, "select count(*) n from users")[0]["n"] == 0
    assert sql(migrated_db, "select count(*) n from auth_flows")[0]["n"] == 0


def test_id_08_verified_password_account_is_never_silently_linked(
    oauth_core: tuple[TestClient, MockIssuer], migrated_db: str
) -> None:
    client, fake = oauth_core
    uid = password_user(migrated_db)
    response = finish(client, fake, start(client))
    assert response.headers["location"] == "/login?error=account_exists"
    assert sql(migrated_db, "select id from users") == [{"id": uid}]
    assert sql(migrated_db, "select count(*) n from user_identities")[0]["n"] == 0


def test_id_08_same_authenticated_account_links_and_revokes_old_sessions(
    oauth_core: tuple[TestClient, MockIssuer], migrated_db: str
) -> None:
    client, fake = oauth_core
    uid = password_user(migrated_db)
    credentials = {"email": "local@gmail.com", "password": PASSWORD}
    assert client.post("/v1/auth/login", json=credentials, headers=CSRF).status_code == 200
    old = client.cookies.get("pramana_session")
    response = finish(client, fake, start(client))
    assert response.headers["location"] == "/app"
    assert client.cookies.get("pramana_session") != old
    assert client.get("/v1/auth/session").json()["user_id"] == uid
    assert sql(migrated_db, "select count(*) n from sessions")[0]["n"] == 1
    client.cookies.clear()
    client.cookies.set("pramana_session", old)
    assert client.get("/v1/auth/session").status_code == 401


def test_id_09_unverified_pre_registration_is_replaced(
    oauth_core: tuple[TestClient, MockIssuer], migrated_db: str
) -> None:
    client, fake = oauth_core
    old_id = password_user(migrated_db)
    sql(migrated_db, "update users set email_verified_at = null")
    client.post(
        "/v1/auth/login", json={"email": "local@gmail.com", "password": PASSWORD}, headers=CSRF
    )
    stolen = client.cookies.get("pramana_session")
    client.cookies.clear()
    assert finish(client, fake, start(client)).headers["location"] == "/app"
    assert client.get("/v1/auth/session").json()["user_id"] != old_id
    assert sql(migrated_db, "select password_hash from users") == [{"password_hash": None}]
    client.cookies.clear()
    client.cookies.set("pramana_session", stolen)
    assert client.get("/v1/auth/session").status_code == 401


def test_id_10_email_change_uses_sub_and_writes_audit(
    oauth_core: tuple[TestClient, MockIssuer], migrated_db: str
) -> None:
    client, fake = oauth_core
    finish(client, fake, start(client))
    uid = client.get("/v1/auth/session").json()["user_id"]
    fake.claims["email"] = "renamed@gmail.com"
    finish(client, fake, start(client))
    me = client.get("/v1/auth/session").json()
    assert me["user_id"] == uid
    assert me["email"] == "renamed@gmail.com"
    assert sql(migrated_db, "select count(*) n from users")[0]["n"] == 1
    assert (
        sql(
            migrated_db, "select count(*) n from audit_log where action = 'identity.email_changed'"
        )[0]["n"]
        == 1
    )


def test_id_11_disabled_account_cannot_sign_in_again(
    oauth_core: tuple[TestClient, MockIssuer], migrated_db: str
) -> None:
    client, fake = oauth_core
    finish(client, fake, start(client))
    sql(migrated_db, "update users set active = false")
    assert (
        finish(client, fake, start(client)).headers["location"] == "/login?error=account_disabled"
    )
    assert client.get("/v1/auth/session").status_code == 401


def test_id_12_personal_and_work_identities_stay_separate(
    oauth_core: tuple[TestClient, MockIssuer], migrated_db: str
) -> None:
    client, fake = oauth_core
    finish(client, fake, start(client))
    first = client.get("/v1/auth/session").json()["user_id"]
    fake.claims.update(sub="work-user", email="staff@college.edu", hd="college.edu")
    finish(client, fake, start(client))
    assert client.get("/v1/auth/session").json()["user_id"] != first
    assert sql(migrated_db, "select count(*) n from users")[0]["n"] == 2


@pytest.mark.parametrize("column", ["idle_expires_at", "absolute_expires_at"])
def test_id_13_session_deadlines_are_enforced(
    oauth_core: tuple[TestClient, MockIssuer], migrated_db: str, column: str
) -> None:
    client, fake = oauth_core
    finish(client, fake, start(client))
    sql(migrated_db, f"update sessions set {column} = now() - interval '1 second'")
    assert client.get("/v1/auth/session").status_code == 401


def test_logout_clears_site_data(oauth_core: tuple[TestClient, MockIssuer]) -> None:
    client, fake = oauth_core
    finish(client, fake, start(client))
    response = client.post("/v1/auth/logout", headers=CSRF)
    assert response.status_code == 204
    assert response.headers["clear-site-data"] == '"cache", "cookies", "storage"'


@pytest.mark.parametrize("error", ["access_denied", "server_error"])
def test_id_16_provider_error_consumes_flow(
    oauth_core: tuple[TestClient, MockIssuer], migrated_db: str, error: str
) -> None:
    client, _ = oauth_core
    query = start(client)
    response = client.get(
        "/v1/auth/google/callback",
        params={"state": query["state"], "error": error},
        follow_redirects=False,
    )
    assert response.headers["location"] in {"/login?error=cancelled", "/login?error=sign_in_failed"}
    assert sql(migrated_db, "select count(*) n from auth_flows")[0]["n"] == 0


def test_id_16_bad_state_consumes_flow(
    oauth_core: tuple[TestClient, MockIssuer], migrated_db: str
) -> None:
    client, fake = oauth_core
    query = start(client)
    query["state"] = "stale-state"
    assert finish(client, fake, query).headers["location"] == "/login?error=sign_in_failed"
    assert sql(migrated_db, "select count(*) n from auth_flows")[0]["n"] == 0


def test_id_17_callback_is_single_use(oauth_core: tuple[TestClient, MockIssuer]) -> None:
    client, fake = oauth_core
    query = start(client)
    cookie = client.cookies.get("pramana_auth")
    code = fake.issue_code(query)
    params = {"state": query["state"], "code": code}
    assert (
        client.get("/v1/auth/google/callback", params=params, follow_redirects=False).headers[
            "location"
        ]
        == "/app"
    )
    client.cookies.set("pramana_auth", cookie)
    response = client.get("/v1/auth/google/callback", params=params, follow_redirects=False)
    assert response.headers["location"] == "/login?error=sign_in_failed"
    assert sum(path == "/token" for _, path in fake.requests) == 1


@pytest.mark.parametrize(
    "path", ["https://evil.example", "//evil.example", "/\\evil.example", "/%2f%2fevil.example"]
)
def test_next_path_never_leaves_origin(
    oauth_core: tuple[TestClient, MockIssuer], path: str
) -> None:
    client, fake = oauth_core
    assert finish(client, fake, start(client, path)).headers["location"] == "/app"


def second_app(client: TestClient, fake: MockIssuer, sim_app: FastAPI) -> TestClient:
    return TestClient(
        create_app(
            client.app.state.settings,
            sim_transport=httpx.ASGITransport(app=sim_app),
            oidc_transport=httpx.MockTransport(fake.transport),
        )
    )


def test_id_15_failed_password_limit_is_shared_across_instances(
    oauth_core: tuple[TestClient, MockIssuer],
    migrated_db: str,
    sim_app: FastAPI,
) -> None:
    client, fake = oauth_core
    password_user(migrated_db)
    bad = {"email": "local@gmail.com", "password": "wrong password"}
    assert client.post("/v1/auth/login", json=bad, headers=CSRF).status_code == 401
    with second_app(client, fake, sim_app) as other:
        assert other.post("/v1/auth/login", json=bad, headers=CSRF).status_code == 401
        assert other.post("/v1/auth/login", json=bad, headers=CSRF).status_code == 401
    assert (
        client.post("/v1/auth/login", json={**bad, "password": PASSWORD}, headers=CSRF).status_code
        == 429
    )


def test_devices_and_sign_out_other_devices(
    oauth_core: tuple[TestClient, MockIssuer],
    sim_app: FastAPI,
) -> None:
    client, fake = oauth_core
    finish(client, fake, start(client))
    first_token = client.cookies.get("pramana_session")
    with second_app(client, fake, sim_app) as other:
        finish(other, fake, start(other))
        second_token = other.cookies.get("pramana_session")
        response = client.get("/v1/auth/devices")
        devices = response.json()
        assert response.headers["cache-control"] == "no-store"
        assert len(devices) == 2
        assert sum(device["current"] for device in devices) == 1
        assert first_token not in response.text
        assert second_token not in response.text
        assert client.post("/v1/auth/devices/revoke-others").status_code == 403
        assert client.post("/v1/auth/devices/revoke-others", headers=CSRF).status_code == 204
        assert other.get("/v1/auth/session").status_code == 401
        assert client.get("/v1/auth/session").status_code == 200


def test_device_revocation_cannot_target_another_user(
    oauth_core: tuple[TestClient, MockIssuer],
    sim_app: FastAPI,
) -> None:
    client, fake = oauth_core
    finish(client, fake, start(client))
    fake.claims.update(sub="other-user", email="other@gmail.com")
    with second_app(client, fake, sim_app) as other:
        finish(other, fake, start(other))
        foreign = other.get("/v1/auth/devices").json()[0]["id"]
        assert client.delete(f"/v1/auth/devices/{foreign}", headers=CSRF).status_code == 204
        assert other.get("/v1/auth/session").status_code == 200


def test_secure_cookies_use_host_prefix(oauth_core: tuple[TestClient, MockIssuer]) -> None:
    client, fake = oauth_core
    client.base_url = "https://testserver"
    client.app.state.settings.session_cookie_secure = True
    query = start(client)
    assert client.cookies.get("__Host-pramana_auth")
    response = finish(client, fake, query)
    headers = response.headers.get_list("set-cookie")
    session_cookie = next(value for value in headers if value.startswith("__Host-pramana_session="))
    assert "Secure" in session_cookie
    assert "HttpOnly" in session_cookie
    assert "Path=/" in session_cookie
    assert "Domain=" not in session_cookie
    assert client.get("/v1/auth/session").status_code == 200


def test_bad_signature_cannot_create_an_account(oauth_core: tuple[TestClient, MockIssuer]) -> None:
    client, fake = oauth_core
    fake.token_key = RSAKey.generate_key(2048, parameters={"kid": fake.key.kid})
    assert finish(client, fake, start(client)).headers["location"] == "/login?error=sign_in_failed"
    assert client.get("/v1/auth/session").status_code == 401


def test_jwks_cache_and_expiry_support_key_rotation(
    oauth_core: tuple[TestClient, MockIssuer],
) -> None:
    client, fake = oauth_core
    fake.jwks_headers = {"cache-control": "max-age=0"}
    finish(client, fake, start(client))
    fake.key = RSAKey.generate_key(2048, parameters={"kid": "rotated-key"})
    assert finish(client, fake, start(client)).headers["location"] == "/app"
    assert sum(path == "/jwks" for _, path in fake.requests) == 2


def test_jwks_cache_honors_max_age(oauth_core: tuple[TestClient, MockIssuer]) -> None:
    client, fake = oauth_core
    finish(client, fake, start(client))
    finish(client, fake, start(client))
    assert sum(path == "/jwks" for _, path in fake.requests) == 1


@pytest.mark.parametrize(
    "headers",
    [
        {"cache-control": "max-age=3600, no-store"},
        {"cache-control": "max-age=3600", "age": "3601"},
    ],
)
def test_jwks_no_store_and_age_are_honored(
    oauth_core: tuple[TestClient, MockIssuer],
    headers: dict[str, str],
) -> None:
    client, fake = oauth_core
    fake.jwks_headers = headers
    finish(client, fake, start(client))
    finish(client, fake, start(client))
    assert sum(path == "/jwks" for _, path in fake.requests) == 2


def test_expired_auth_flow_is_consumed(
    oauth_core: tuple[TestClient, MockIssuer], migrated_db: str
) -> None:
    client, fake = oauth_core
    query = start(client)
    sql(migrated_db, "update auth_flows set expires_at = now() - interval '1 second'")
    assert finish(client, fake, query).headers["location"] == "/login?error=sign_in_failed"
    assert sql(migrated_db, "select count(*) n from auth_flows")[0]["n"] == 0


def test_switch_account_sets_prompt_and_login_hint(
    oauth_core: tuple[TestClient, MockIssuer],
) -> None:
    client, _ = oauth_core
    response = client.get(
        "/v1/auth/google/start",
        params={"switch_account": "true", "login_hint": "staff@college.edu"},
        follow_redirects=False,
    )
    query = dict(parse_qsl(urlsplit(response.headers["location"]).query))
    assert query["prompt"] == "select_account"
    assert query["login_hint"] == "staff@college.edu"


def test_id_14_event_stream_ends_after_logout(migrated_db: str, sim_app: FastAPI) -> None:
    asyncio.run(truncate_all(migrated_db))
    password_user(migrated_db)
    app = create_app(
        core_settings(
            migrated_db,
            AUTH_REQUIRED=True,
            EVENT_STREAM_HEARTBEAT_S=0.1,
            EVENT_STREAM_MAX_S=5,
            CORE_AUTOMATION_KEY="",
        ),
        sim_transport=httpx.ASGITransport(app=sim_app),
    )
    with serve(app) as url, httpx.Client(base_url=url, timeout=10) as client:
        result = client.post(
            "/v1/auth/login", json={"email": "local@gmail.com", "password": PASSWORD}, headers=CSRF
        )
        assert result.status_code == 200
        response = client.post(
            "/v1/investigations", json=body(fault="CB_C2_7.tripped"), headers=CSRF
        )
        assert response.status_code == 201
        inv_id = response.json()["id"]
        with client.stream("GET", f"/v1/investigations/{inv_id}/stream") as response:
            stream = read_sse(response)
            for message in stream:
                if message.event == "ready":
                    break
            assert client.post("/v1/auth/logout", headers=CSRF).status_code == 204
            for message in stream:
                if message.event == "bye":
                    assert message.data["reason"] == "signed_out"
                    break
            else:
                pytest.fail("the stream did not report session revocation")
