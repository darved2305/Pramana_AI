"""Local-only OIDC issuer for browser development. Never use it with production mode.

    uv run python scripts/mock_oidc.py --port 8410

Configure OIDC_ISSUER=http://localhost:8410, OIDC_DISCOVERY_URL with its
/.well-known/openid-configuration path, a dummy GOOGLE_OAUTH_CLIENT_ID and
GOOGLE_OAUTH_CLIENT_SECRET=local-only. Keys and authorization codes are ephemeral.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from joserfc import jwt
from joserfc.jwk import RSAKey


class MockIssuer:
    """Used both by the local app and an in-process httpx.MockTransport in pytest."""

    def __init__(self, issuer: str = "http://localhost:8410", client_id: str = "pramana-local"):
        self.issuer, self.client_id = issuer.rstrip("/"), client_id
        self.key = RSAKey.generate_key(2048, parameters={"kid": "mock-key"})
        self.token_key: RSAKey | None = None
        self.codes: dict[str, dict[str, Any]] = {}
        self.claims: dict[str, Any] = {
            "sub": "local-user",
            "email": "local@gmail.com",
            "email_verified": True,
            "name": "Local user",
        }
        self.overrides: dict[str, Any] = {}
        self.token_error = False
        self.requests: list[tuple[str, str]] = []
        self.jwks_headers = {"cache-control": "public, max-age=3600"}

    def discovery(self) -> dict[str, Any]:
        return {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/authorize",
            "token_endpoint": f"{self.issuer}/token",
            "jwks_uri": f"{self.issuer}/jwks",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
            "code_challenge_methods_supported": ["S256"],
        }

    def issue_code(self, query: dict[str, str], claims: dict[str, Any] | None = None) -> str:
        code = secrets.token_urlsafe(32)
        self.codes[code] = {
            **query,
            "claims": dict(claims or self.claims),
            "expires": time.time() + 600,
        }
        return code

    def token(self, form: dict[str, str]) -> tuple[int, dict[str, Any]]:
        data = self.codes.pop(form.get("code", ""), None)
        verifier = form.get("code_verifier", "")
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        if (
            self.token_error
            or data is None
            or data["expires"] <= time.time()
            or form.get("grant_type") != "authorization_code"
            or form.get("client_id") != self.client_id
            or form.get("client_secret") != "local-only"
            or form.get("redirect_uri") != data["redirect_uri"]
            or digest != data["code_challenge"]
        ):
            return 400, {"error": "invalid_grant"}
        now = int(time.time())
        claims = {
            "iss": self.issuer,
            "aud": self.client_id,
            "iat": now,
            "exp": now + 300,
            "nonce": data["nonce"],
            **data["claims"],
            **self.overrides,
        }
        encoded = jwt.encode(
            {"alg": "RS256", "kid": self.key.kid}, claims, self.token_key or self.key
        )
        return 200, {"id_token": encoded, "token_type": "Bearer"}

    def transport(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == "/.well-known/openid-configuration":
            return httpx.Response(200, json=self.discovery())
        if request.method == "GET" and request.url.path == "/jwks":
            return httpx.Response(
                200, json={"keys": [self.key.as_dict(private=False)]}, headers=self.jwks_headers
            )
        if request.method == "POST" and request.url.path == "/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            status, data = self.token(form)
            return httpx.Response(status, json=data)
        return httpx.Response(404)


def create_app(issuer: str = "http://localhost:8410", client_id: str = "pramana-local") -> FastAPI:
    fake = MockIssuer(issuer, client_id)
    app = FastAPI(title="Pramana local mock sign-in")
    app.state.issuer = fake

    @app.get("/.well-known/openid-configuration")
    async def discovery() -> dict[str, Any]:
        return fake.discovery()

    @app.get("/jwks")
    async def keys() -> JSONResponse:
        return JSONResponse({"keys": [fake.key.as_dict(private=False)]}, headers=fake.jwks_headers)

    @app.post("/token")
    async def token(request: Request) -> JSONResponse:
        values = await request.form()
        status, data = fake.token({k: str(v) for k, v in values.items()})
        return JSONResponse(data, status_code=status)

    @app.get("/authorize", response_model=None)
    async def authorize(request: Request) -> HTMLResponse | RedirectResponse | JSONResponse:
        query = dict(request.query_params)
        redirect = urlsplit(query.get("redirect_uri", ""))
        if (
            redirect.scheme != "http"
            or redirect.hostname not in {"localhost", "127.0.0.1"}
            or redirect.username
            or redirect.password
            or redirect.fragment
            or query.get("client_id") != fake.client_id
            or query.get("response_type") != "code"
            or query.get("code_challenge_method") != "S256"
            or not all(query.get(k) for k in ("state", "nonce", "code_challenge"))
        ):
            return JSONResponse({"error": "invalid_request"}, status_code=400)
        if query.get("approve") != "1":
            hidden = "".join(
                f'<input type="hidden" name="{html.escape(k, quote=True)}" '
                f'value="{html.escape(v, quote=True)}">'
                for k, v in query.items()
                if k not in {"sub", "email", "hd", "name", "approve", "email_verified"}
            )
            return HTMLResponse(
                '<!doctype html><html lang="en"><meta charset="utf-8"><title>Mock sign-in</title>'
                "<h1>Pramana local mock sign-in</h1><p>This is a simulated identity provider.</p>"
                f'<form method="get">{hidden}<input type="hidden" name="approve" value="1">'
                '<p><label>Subject <input name="sub" value="local-user" required></label></p>'
                '<p><label>Email <input name="email" value="local@gmail.com" required></label></p>'
                '<p><label>Name <input name="name" value="Local user" required></label></p>'
                '<p><label>Workspace domain <input name="hd"></label></p>'
                '<p><label><input type="checkbox" name="email_verified" value="true" checked>'
                "Email verified</label></p>"
                '<button type="submit">Continue with mock account</button></form></html>'
            )
        claims: dict[str, Any] = {
            "sub": query.get("sub", "local-user"),
            "email": query.get("email", "local@gmail.com"),
            "email_verified": query.get("email_verified") == "true",
            "name": query.get("name", "Local user"),
        }
        if query.get("hd"):
            claims["hd"] = query["hd"]
        code = fake.issue_code(query, claims)
        params = urlencode({"code": code, "state": query["state"]})
        return RedirectResponse(f"{query['redirect_uri']}?{params}", status_code=302)

    return app


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8410)
    parser.add_argument("--client-id", default="pramana-local")
    args = parser.parse_args()
    uvicorn.run(
        create_app(f"http://localhost:{args.port}", args.client_id),
        host="127.0.0.1",
        port=args.port,
    )
