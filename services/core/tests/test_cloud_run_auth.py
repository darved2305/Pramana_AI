from __future__ import annotations

import asyncio
import base64
import json
import time

import httpx

from pramana_core.cloud_run import METADATA_IDENTITY_URL, CloudRunIdentityToken
from pramana_core.sim_client import SimClient


def _token(expiry: int) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": expiry}).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def test_cloud_run_identity_uses_metadata_and_caches() -> None:
    requests: list[httpx.Request] = []
    token = _token(int(time.time()) + 3600)

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, text=token)

    async def check() -> None:
        identity = CloudRunIdentityToken(
            "https://sim-123.asia-south1.run.app", transport=httpx.MockTransport(respond)
        )
        try:
            assert await identity.header() == {"X-Serverless-Authorization": f"Bearer {token}"}
            assert await identity.header() == {"X-Serverless-Authorization": f"Bearer {token}"}
        finally:
            await identity.aclose()

    asyncio.run(check())
    assert len(requests) == 1
    assert str(requests[0].url).startswith(METADATA_IDENTITY_URL)
    assert requests[0].url.params["audience"] == "https://sim-123.asia-south1.run.app"
    assert requests[0].headers["Metadata-Flavor"] == "Google"


def test_sim_client_keeps_operator_secret_separate_from_serverless_token() -> None:
    service_requests: list[httpx.Request] = []
    token = _token(int(time.time()) + 3600)

    def metadata(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=token)

    def simulator(request: httpx.Request) -> httpx.Response:
        service_requests.append(request)
        return httpx.Response(200, json={"status": "ok"})

    async def check() -> None:
        client = SimClient(
            "https://sim-123.asia-south1.run.app",
            "operator-key",
            3,
            transport=httpx.MockTransport(simulator),
            service_auth=True,
            identity_transport=httpx.MockTransport(metadata),
        )
        try:
            assert await client.health()
        finally:
            await client.aclose()

    asyncio.run(check())
    headers = service_requests[0].headers
    assert headers["X-Serverless-Authorization"] == f"Bearer {token}"
    assert headers["X-Operator-Key"] == "operator-key"
    assert "Authorization" not in headers
