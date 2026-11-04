from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pramana_contracts.tokens import (
    TokenError,
    generate_private_key_b64,
    mint,
    private_key_from_b64,
    public_key_b64,
    public_key_from_b64,
    verify,
)


def test_round_trip_through_base64_keys() -> None:
    key = private_key_from_b64(generate_private_key_b64())
    pub = public_key_from_b64(public_key_b64(key))
    claims = verify(pub, mint(key, participant_id="p_riya", scenario_id="sc_1"))
    assert (claims.sub, claims.scn, claims.aud) == ("p_riya", "sc_1", "sim")


def test_tampered_payload_is_rejected() -> None:
    key = Ed25519PrivateKey.generate()
    body, sig = mint(key, participant_id="p_riya", scenario_id="sc_1").split(".")
    forged_body = mint(key, participant_id="p_admin", scenario_id="sc_1").split(".")[0]
    with pytest.raises(TokenError):
        verify(key.public_key(), f"{forged_body}.{sig}")
    with pytest.raises(TokenError):
        verify(key.public_key(), body)


def test_expiry_and_audience() -> None:
    key = Ed25519PrivateKey.generate()
    tok = mint(key, participant_id="p", scenario_id="s", ttl_s=60, now=1000)
    assert verify(key.public_key(), tok, now=1059).sub == "p"
    with pytest.raises(TokenError, match="expired"):
        verify(key.public_key(), tok, now=1061)
    with pytest.raises(TokenError, match="audience"):
        verify(key.public_key(), tok, aud="core", now=1000)
