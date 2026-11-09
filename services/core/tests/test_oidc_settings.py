"""Production identity configuration cannot silently select a mock or bypass."""

from __future__ import annotations

import asyncio
from pathlib import Path
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
        core_settings("postgresql+asyncpg://pramana_app@localhost:5433/pramana_prod_test", **values)
    assert "test-sensitive-value" not in str(caught.value)


def test_production_uses_host_cookies_and_google() -> None:
    cfg = core_settings(
        "postgresql+asyncpg://pramana_app@localhost:5433/pramana_prod_test",
        PRAMANA_MODE="production",
        CORE_AUTOMATION_KEY="",
        OIDC_ISSUER="https://accounts.google.com",
        OIDC_DISCOVERY_URL="https://accounts.google.com/.well-known/openid-configuration",
        OIDC_REDIRECT_URL="https://pramana.example/api/core/v1/auth/google/callback",
        PRAMANA_PII_KEY="AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8",
    )
    assert cfg.enforce_auth
    assert cfg.secure_cookies
    assert cfg.session_cookie_name == "__Host-pramana_session"
    assert cfg.auth_flow_cookie_name == "__Host-pramana_auth"


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


def test_core_test_settings_ignore_the_checkout_env_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Settings read ``.env`` from the working directory. A checkout's local values must not reach
    # the tests, or they pass or fail depending on that file.
    (tmp_path / ".env").write_text("OIDC_ISSUER=https://evil.example\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OIDC_ISSUER", raising=False)
    settings = core_settings("postgresql+asyncpg://pramana@localhost:5433/pramana_test")
    assert settings.oidc_issuer == "https://accounts.google.com"
