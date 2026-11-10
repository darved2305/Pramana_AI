from __future__ import annotations

import httpx
import pytest
from core_testkit import core_settings
from pydantic import SecretStr

from pramana_contracts.tokens import generate_private_key_b64, private_key_from_b64, public_key_b64
from pramana_core.main import create_app
from pramana_sim.app import SimSettings
from pramana_sim.app import create_app as create_sim_app


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path",
    [
        "/v1/consent-links/test",
        "/v1/auth/login",
        "/v1/orgs/test/sites",
        "/v1/voice/stt",
        "/v1/orgs/test/investigations/test/answers/voice",
    ],
)
@pytest.mark.parametrize("lying_length", [False, True])
async def test_oversized_stream_rejected_before_auth(path: str, lying_length: bool) -> None:
    app = create_app(core_settings("postgresql+asyncpg://localhost/unused"))
    consumed = 0

    async def body():
        nonlocal consumed
        for _ in range(100):
            consumed += 1
            yield b"x" * 65536

    headers = {"content-length": "1"} if lying_length else {}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(path, content=body(), headers=headers)
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "BODY_TOO_LARGE"
    assert consumed < 100


@pytest.mark.anyio
async def test_simulator_rejects_oversized_stream_before_auth() -> None:
    key = private_key_from_b64(generate_private_key_b64())
    app = create_sim_app(
        SimSettings(operator_key=SecretStr("test"), participant_public_key=public_key_b64(key))
    )

    async def body():
        for _ in range(80):
            yield b"x" * 65536

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/sim/v1/scenarios", content=body(), headers={"content-length": "1"}
        )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "BODY_TOO_LARGE"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_cors_preflight_is_also_limited() -> None:
    app = create_app(
        core_settings("postgresql+asyncpg://localhost/unused", CORS_ORIGINS=["http://example.test"])
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(
            "OPTIONS",
            "/v1/auth/login",
            content=b"x" * 65537,
            headers={"Origin": "http://example.test", "Access-Control-Request-Method": "POST"},
        )
    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == "http://example.test"
