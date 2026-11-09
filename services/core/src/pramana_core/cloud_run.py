"""Fetch and cache Cloud Run service identity tokens from the metadata server."""

from __future__ import annotations

import base64
import json
import time

import httpx

METADATA_IDENTITY_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity"
)


class CloudRunIdentityToken:
    def __init__(
        self,
        audience: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._audience = audience.rstrip("/")
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(3.0),
            transport=transport,
            trust_env=False,
        )
        self._token: str | None = None
        self._expires_at = 0.0

    async def header(self) -> dict[str, str]:
        now = time.time()
        if self._token is None or now >= self._expires_at:
            response = await self._http.get(
                METADATA_IDENTITY_URL,
                params={"audience": self._audience, "format": "full"},
                headers={"Metadata-Flavor": "Google"},
            )
            response.raise_for_status()
            token = response.text.strip()
            if not token:
                raise RuntimeError("Cloud Run metadata server returned an empty identity token")
            self._token = token
            self._expires_at = self._expiry(token, now)
        return {"X-Serverless-Authorization": f"Bearer {self._token}"}

    @staticmethod
    def _expiry(token: str, now: float) -> float:
        try:
            segment = token.split(".")[1]
            payload = json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))
            expiry = payload.get("exp")
            if isinstance(expiry, (float, int)):
                return max(now, float(expiry) - 60)
        except (IndexError, ValueError, TypeError, json.JSONDecodeError):
            pass
        return now + 3000

    async def aclose(self) -> None:
        await self._http.aclose()
