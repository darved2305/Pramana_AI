"""The local browser issuer runs without Docker or external credentials."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

from fastapi.testclient import TestClient

from pramana_core.auth.oidc import challenge

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from mock_oidc import create_app


def test_mock_browser_authorization_and_pkce_exchange() -> None:
    with TestClient(create_app()) as client:
        discovery = client.get("/.well-known/openid-configuration").json()
        assert discovery["issuer"] == "http://localhost:8410"
        assert client.get("/jwks").json()["keys"][0]["kty"] == "RSA"
        query = {
            "client_id": "pramana-local",
            "redirect_uri": "http://localhost:3102/callback",
            "response_type": "code",
            "state": "state-value",
            "nonce": "nonce-value",
            "code_challenge_method": "S256",
            "code_challenge": challenge("v" * 43),
        }
        page = client.get("/authorize", params=query)
        assert page.status_code == 200
        assert "simulated identity provider" in page.text
        response = client.get(
            "/authorize",
            params={**query, "approve": "1", "email_verified": "true"},
            follow_redirects=False,
        )
        returned = dict(parse_qsl(urlsplit(response.headers["location"]).query))
        form = {
            "grant_type": "authorization_code",
            "code": returned["code"],
            "client_id": "pramana-local",
            "client_secret": "local-only",
            "redirect_uri": query["redirect_uri"],
            "code_verifier": "v" * 43,
        }
        assert client.post("/token", data=form).status_code == 200
        assert client.post("/token", data=form).status_code == 400


def test_mock_browser_never_redirects_to_an_external_site() -> None:
    with TestClient(create_app()) as client:
        assert (
            client.get("/authorize", params={"redirect_uri": "https://evil.example"}).status_code
            == 400
        )
