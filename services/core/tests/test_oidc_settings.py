"""Production identity configuration cannot silently select a mock or bypass."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from core_testkit import core_settings
from pydantic import ValidationError
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from pramana_core.db import Database


@pytest.mark.parametrize(
    "override",
    [
        {"OIDC_ISSUER": "http://localhost:8410"},
        {"OIDC_DISCOVERY_URL": "https://evil.example/discovery"},
        {"CORE_AUTOMATION_KEY": "test-sensitive-value"},
        {"AUTH_REQUIRED": False},
        {"SESSION_COOKIE_SECURE": False},
        {"OIDC_REDIRECT_URL": "http://localhost:3102/callback"},
        {"PRAMANA_PII_KEY": None},
    ],
)
def test_production_refuses_auth_bypasses(override: dict[str, Any]) -> None:
    values = {
        "PRAMANA_MODE": "production",
        "CORE_AUTOMATION_KEY": "",
        "OIDC_ISSUER": "https://accounts.google.com",
        "OIDC_DISCOVERY_URL": "https://accounts.google.com/.well-known/openid-configuration",
        "OIDC_REDIRECT_URL": "https://pramana.example/api/core/v1/auth/google/callback",
        "GOOGLE_OAUTH_CLIENT_SECRET": "test-sensitive-value",
        "PRAMANA_PII_KEY": "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
        **override,
    }
    with pytest.raises(ValidationError) as caught:
        core_settings(
            "postgresql+asyncpg://pramana_app@db.example:5432/pramana_prod_test", **values
        )
    assert "test-sensitive-value" not in str(caught.value)


def test_production_uses_host_cookies_and_google() -> None:
    cfg = core_settings(
        "postgresql+asyncpg://pramana_app@db.example:5432/pramana_prod_test",
        PRAMANA_MODE="production",
        CORE_AUTOMATION_KEY="",
        OIDC_REDIRECT_URL="https://pramana.example/api/core/v1/auth/google/callback",
        PRAMANA_PII_KEY="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
    )
    assert cfg.enforce_auth
    assert cfg.secure_cookies
    assert cfg.session_cookie_name == "__Host-pramana_session"
    assert cfg.auth_flow_cookie_name == "__Host-pramana_auth"


def test_local_production_harness_requires_the_docker_only_endpoints() -> None:
    cfg = core_settings(
        "postgresql+asyncpg://pramana_app@host.docker.internal:5433/pramana_prod_test",
        PRAMANA_MODE="production",
        PRAMANA_LOCAL_PRODUCTION_TEST=True,
        PRAMANA_PII_KEY="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
        OIDC_ISSUER="http://localhost:8420",
        OIDC_DISCOVERY_URL="http://host.docker.internal:8420/.well-known/openid-configuration",
        OIDC_REDIRECT_URL="http://localhost:3100/api/core/v1/auth/google/callback",
        SIM_URL="http://sim:8080",
        SIM_SERVERLESS_AUTH=False,
    )
    assert cfg.mode == "production"
    assert cfg.enforce_auth
    assert cfg.secure_cookies


def test_local_production_harness_accepts_isolated_docker_service_names() -> None:
    cfg = core_settings(
        "postgresql+asyncpg://pramana_app@postgres:5432/pramana_prod_test",
        PRAMANA_MODE="production",
        PRAMANA_LOCAL_PRODUCTION_TEST=True,
        PRAMANA_PII_KEY="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
        OIDC_ISSUER="http://localhost:8420",
        OIDC_DISCOVERY_URL="http://mock-oidc:8420/.well-known/openid-configuration",
        OIDC_REDIRECT_URL="http://localhost:3100/api/core/v1/auth/google/callback",
        SIM_URL="http://sim:8080",
        SIM_SERVERLESS_AUTH=False,
    )
    assert cfg.mode == "production"
    assert cfg.enforce_auth
    assert cfg.secure_cookies


def test_production_runtime_role_cannot_bypass_rls(migrated_db: str) -> None:
    async def check() -> None:
        owner = Database(create_async_engine(migrated_db))
        try:
            with pytest.raises(RuntimeError, match="non-superuser"):
                await owner.require_runtime_role()
        finally:
            await owner.dispose()
        url = (
            make_url(migrated_db)
            .set(username="pramana_app", password=None)
            .render_as_string(hide_password=False)
        )
        runtime = Database(create_async_engine(url))
        try:
            await runtime.require_runtime_role()
        finally:
            await runtime.dispose()

    asyncio.run(check())
