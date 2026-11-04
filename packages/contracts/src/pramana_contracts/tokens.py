"""Signed participant tokens (wire format shared by the core, which mints, and the simulator,
which verifies).

Format: ``base64url(json payload) "." base64url(Ed25519 signature over the first part)``.
The core holds the private key; the simulator is configured with the public key only, so a
compromised simulator cannot mint identities. Payload fields: ``sub`` (participant id), ``scn``
(scenario id), ``aud`` (intended audience), ``exp`` (unix seconds), ``jti`` (unique id).
"""

from __future__ import annotations

import base64
import json
import secrets
import time
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


class TokenError(ValueError):
    """The token is malformed, forged, expired, or meant for someone else."""


@dataclass(frozen=True)
class ParticipantClaims:
    sub: str
    scn: str
    aud: str
    exp: int
    jti: str


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def private_key_from_b64(value: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(_b64d(value))


def public_key_from_b64(value: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(_b64d(value))


def public_key_b64(key: Ed25519PrivateKey) -> str:
    return _b64e(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))


def mint(
    key: Ed25519PrivateKey,
    *,
    participant_id: str,
    scenario_id: str,
    aud: str = "sim",
    ttl_s: int = 12 * 3600,
    now: float | None = None,
) -> str:
    claims = {
        "typ": "participant",
        "sub": participant_id,
        "scn": scenario_id,
        "aud": aud,
        "exp": int((now if now is not None else time.time()) + ttl_s),
        "jti": secrets.token_hex(8),
    }
    return _sign(key, claims)


def _sign(key: Ed25519PrivateKey, claims: dict[str, object]) -> str:
    body = _b64e(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode())
    return f"{body}.{_b64e(key.sign(body.encode()))}"


def _open(key: Ed25519PublicKey, token: str) -> dict[str, object]:
    try:
        body, sig = token.split(".")
        key.verify(_b64d(sig), body.encode())
        data: dict[str, object] = json.loads(_b64d(body))
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise TokenError("invalid token") from exc
    return data


def verify(
    key: Ed25519PublicKey, token: str, *, aud: str = "sim", now: float | None = None
) -> ParticipantClaims:
    data = _open(key, token)
    if data.get("typ", "participant") != "participant":
        raise TokenError("not a participant token")
    try:
        claims = ParticipantClaims(
            sub=str(data["sub"]),
            scn=str(data["scn"]),
            aud=str(data["aud"]),
            exp=int(str(data["exp"])),
            jti=str(data["jti"]),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise TokenError("invalid token") from exc
    if claims.aud != aud:
        raise TokenError("token audience mismatch")
    if claims.exp < (now if now is not None else time.time()):
        raise TokenError("token expired")
    return claims


def generate_private_key_b64() -> str:
    key = Ed25519PrivateKey.generate()
    return _b64e(key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption()))


@dataclass(frozen=True)
class CapabilityClaims:
    """Permission to perform one approved action on one target, once, for a short time."""

    jti: str
    scn: str
    inv: str
    sub: str
    act: str
    tgt: str
    exp: int


def mint_capability(
    key: Ed25519PrivateKey,
    *,
    scenario_id: str,
    investigation_id: str,
    participant_id: str,
    action: str,
    target: str,
    ttl_s: int = 300,
    now: float | None = None,
) -> tuple[str, CapabilityClaims]:
    claims = CapabilityClaims(
        jti=secrets.token_hex(12),
        scn=scenario_id,
        inv=investigation_id,
        sub=participant_id,
        act=action,
        tgt=target,
        exp=int((now if now is not None else time.time()) + ttl_s),
    )
    token = _sign(key, {"typ": "capability", "aud": "sim", **claims.__dict__})
    return token, claims


def verify_capability(
    key: Ed25519PublicKey, token: str, *, now: float | None = None
) -> CapabilityClaims:
    """Signature, type, audience and expiry. Single use is enforced by the verifier's ledger."""
    data = _open(key, token)
    if data.get("typ") != "capability" or data.get("aud") != "sim":
        raise TokenError("not a capability token for the simulator")
    try:
        claims = CapabilityClaims(
            jti=str(data["jti"]),
            scn=str(data["scn"]),
            inv=str(data["inv"]),
            sub=str(data["sub"]),
            act=str(data["act"]),
            tgt=str(data["tgt"]),
            exp=int(str(data["exp"])),
        )
    except (KeyError, ValueError) as exc:
        raise TokenError("invalid capability") from exc
    if claims.exp < (now if now is not None else time.time()):
        raise TokenError("capability expired")
    return claims
