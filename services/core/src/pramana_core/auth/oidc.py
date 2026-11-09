"""Google authorization-code client. Only discovery-configured keys are trusted.

The transport is injectable for tests. No bearer token, code, secret or claim is logged.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import math
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from ..settings import Settings

GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_DISCOVERY = f"{GOOGLE_ISSUER}/.well-known/openid-configuration"


class OidcError(Exception):
    """A deliberately non-sensitive authentication failure."""


def safe_next(value: str) -> str:
    """Accept an origin-relative path, including neither URL escapes nor control characters."""
    if (
        not value.startswith("/")
        or value.startswith("//")
        or "\\" in value
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
        or "%" in value
        or len(value) > 2048
    ):
        return "/app"
    parsed = urlsplit(value)
    return value if not parsed.scheme and not parsed.netloc else "/app"


def challenge(verifier: str) -> str:
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode()
        .rstrip("=")
    )


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    email_verified: bool
    hosted_domain: str | None
    name: str

    @property
    def authoritative_email(self) -> bool:
        domain = self.email.rsplit("@", 1)[-1]
        return self.email_verified and (domain == "gmail.com" or self.hosted_domain is not None)


class GoogleOidc:
    def __init__(self, cfg: Settings, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.cfg = cfg
        self.http = httpx.AsyncClient(
            transport=transport, timeout=8.0, follow_redirects=False, trust_env=False
        )
        self._metadata: dict[str, Any] | None = None
        self._keys: KeySet | None = None
        self._key_ids: set[str] = set()
        self._keys_until = 0.0
        self._refreshed_at = float("-inf")
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self.http.aclose()

    def _endpoint(self, value: object) -> str:
        if not isinstance(value, str):
            raise OidcError("invalid provider configuration")
        parsed = urlsplit(value)
        if parsed.username or parsed.password or parsed.fragment:
            raise OidcError("invalid provider configuration")
        if self.cfg.oidc_issuer == GOOGLE_ISSUER:
            if (
                parsed.scheme != "https"
                or parsed.hostname
                not in {"accounts.google.com", "oauth2.googleapis.com", "www.googleapis.com"}
                or parsed.port not in (None, 443)
            ):
                raise OidcError("invalid provider configuration")
        elif (
            parsed.scheme != "https"
            and not (
                self.cfg.mode in {"dev", "test"}
                and parsed.scheme == "http"
                and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            )
            and not (
                self.cfg.mode == "production"
                and self.cfg.local_production_test
                and parsed.scheme == "http"
                and parsed.hostname in {"localhost", "127.0.0.1", "host.docker.internal"}
            )
        ):
            raise OidcError("invalid provider configuration")
        return value

    async def metadata(self) -> dict[str, Any]:
        if not self.cfg.google_oauth_client_id or not self.cfg.google_oauth_client_secret:
            raise OidcError("Google sign-in is not configured")
        if self._metadata is None:
            response = await self.http.get(self._endpoint(self.cfg.oidc_discovery_url))
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or data.get("issuer") != self.cfg.oidc_issuer:
                raise OidcError("invalid provider configuration")
            for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
                self._endpoint(data.get(key))
            if "S256" not in data.get("code_challenge_methods_supported", []):
                raise OidcError("provider does not support PKCE S256")
            self._metadata = data
        return self._metadata

    async def authorization_url(
        self,
        state: str,
        nonce: str,
        verifier: str,
        *,
        login_hint: str | None = None,
        switch_account: bool = False,
    ) -> str:
        data = await self.metadata()
        params = {
            "client_id": self.cfg.google_oauth_client_id,
            "redirect_uri": self.cfg.oidc_redirect_url,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge(verifier),
            "code_challenge_method": "S256",
        }
        if login_hint:
            params["login_hint"] = login_hint
        if switch_account:
            params["prompt"] = "select_account"
        return f"{data['authorization_endpoint']}?{urlencode(params)}"

    async def _jwks(self, kid: str) -> KeySet:
        async with self._lock:
            now = time.monotonic()
            expired = self._keys is None or now >= self._keys_until
            # Coalesce refreshes and bound unknown-key misses so forged kids cannot flood Google.
            missing = kid not in self._key_ids and now - self._refreshed_at >= 30
            if expired or missing:
                data = await self.metadata()
                response = await self.http.get(data["jwks_uri"])
                response.raise_for_status()
                raw = response.json()
                eligible = [
                    key
                    for key in raw["keys"]
                    if key.get("kty") == "RSA"
                    and key.get("use", "sig") == "sig"
                    and key.get("alg", "RS256") == "RS256"
                    and "verify" in key.get("key_ops", ["verify"])
                    and isinstance(key.get("kid"), str)
                    and "d" not in key
                ]
                self._keys = KeySet.import_key_set({"keys": eligible})
                self._key_ids = {key["kid"] for key in eligible}
                max_age = re.search(
                    r"(?:^|,)\s*max-age=(\d+)", response.headers.get("cache-control", "")
                )
                ttl = min(int(max_age[1]), 86400) if max_age else 300
                if re.search(
                    r"(?:^|,)\s*(?:no-store|no-cache)(?:\s|,|$)",
                    response.headers.get("cache-control", ""),
                ):
                    ttl = 0
                age = max(0, int(response.headers.get("age", "0")))
                self._keys_until = now + max(0, ttl - age)
                self._refreshed_at = now
            if kid not in self._key_ids or self._keys is None:
                raise OidcError("unrecognized signing key")
            return self._keys

    async def exchange(self, code: str, verifier: str, nonce: str) -> GoogleIdentity:
        try:
            metadata = await self.metadata()
            secret = self.cfg.google_oauth_client_secret
            assert secret is not None
            response = await self.http.post(
                metadata["token_endpoint"],
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self.cfg.google_oauth_client_id,
                    "client_secret": secret.get_secret_value(),
                    "redirect_uri": self.cfg.oidc_redirect_url,
                    "code_verifier": verifier,
                },
            )
            response.raise_for_status()
            encoded = response.json()["id_token"]
            if not isinstance(encoded, str) or len(encoded) > 16384:
                raise OidcError("invalid ID token")
            # Only a key selector is read before verification. Never use a token's jku or jwk.
            header_part = encoded.split(".")[0]
            header = json.loads(
                base64.urlsafe_b64decode(header_part + "=" * (-len(header_part) % 4))
            )
            kid = header.get("kid")
            if header.get("alg") != "RS256" or not isinstance(kid, str) or len(kid) > 256:
                raise OidcError("invalid signing key")
            decoded = jwt.decode(encoded, await self._jwks(kid), algorithms=["RS256"])
            claims = decoded.claims
            self._validate_claims(claims, nonce)
            return GoogleIdentity(
                sub=claims["sub"],
                email=claims["email"].strip().lower(),
                email_verified=claims.get("email_verified") is True,
                hosted_domain=claims.get("hd"),
                name=claims.get("name", "")[:80],
            )
        except (httpx.HTTPError, JoseError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise OidcError("Google sign-in could not be verified") from exc

    def _validate_claims(self, claims: dict[str, Any], nonce: str) -> None:
        if not isinstance(claims.get("iss"), str):
            raise OidcError("invalid issuer")
        audience = claims.get("aud")
        if not isinstance(audience, str) and not (
            isinstance(audience, list) and audience and all(isinstance(a, str) for a in audience)
        ):
            raise OidcError("invalid audience")
        issuers = [self.cfg.oidc_issuer]
        if self.cfg.oidc_issuer == GOOGLE_ISSUER:
            issuers.append("accounts.google.com")
        jwt.JWTClaimsRegistry(
            iss={"essential": True, "values": issuers},
            aud={"essential": True, "value": self.cfg.google_oauth_client_id},
            exp={"essential": True},
            iat={"essential": True},
            sub={"essential": True},
        ).validate(claims)
        for key in ("exp", "iat"):
            if type(claims[key]) not in (int, float) or not math.isfinite(claims[key]):
                raise OidcError("invalid token timestamp")
        if claims["iat"] > time.time() + 60 or claims["exp"] <= claims["iat"]:
            raise OidcError("invalid token timestamp")
        audience = claims["aud"]
        if ("azp" in claims or (isinstance(audience, list) and len(audience) > 1)) and claims.get(
            "azp"
        ) != self.cfg.google_oauth_client_id:
            raise OidcError("invalid authorized party")
        if not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(
            claims["nonce"].encode(), nonce.encode()
        ):
            raise OidcError("invalid nonce")
        sub = claims["sub"]
        if (
            not isinstance(sub, str)
            or not sub.isascii()
            or not 1 <= len(sub) <= 255
            or any(ord(c) < 33 or ord(c) > 126 for c in sub)
        ):
            raise OidcError("invalid subject")
        email = claims.get("email")
        if (
            not isinstance(email, str)
            or len(email) > 254
            or not re.fullmatch(r"[^\s@]{1,64}@[^\s@]{1,253}", email)
        ):
            raise OidcError("invalid email")
        if "email_verified" in claims and type(claims["email_verified"]) is not bool:
            raise OidcError("invalid email verification")
        hd = claims.get("hd")
        if hd is not None and (
            not isinstance(hd, str)
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", hd)
        ):
            raise OidcError("invalid hosted domain")
        if "name" in claims and not isinstance(claims["name"], str):
            raise OidcError("invalid display name")
