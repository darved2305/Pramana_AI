from __future__ import annotations

from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from pramana_contracts.tokens import (
    CAPABILITY_TTL_S,
    CLOCK_SKEW_S,
    PARTICIPANT_TTL_S,
    TokenError,
    generate_private_key_b64,
    mint,
    mint_capability,
    private_key_from_b64,
    public_key_b64,
    public_key_from_b64,
    verify,
    verify_capability,
)


def test_round_trip_through_base64_keys() -> None:
    key = private_key_from_b64(generate_private_key_b64())
    pub = public_key_from_b64(public_key_b64(key))
    claims = verify(pub, mint(key, participant_id="p_riya", scenario_id="sc_1"))
    assert (claims.sub, claims.scn, claims.aud) == ("p_riya", "sc_1", "sim")
    assert claims.org is None  # Existing simulator tokens are still understood.


def test_signed_organization_claim_round_trips() -> None:
    key = Ed25519PrivateKey.generate()
    token = mint(key, participant_id="p", scenario_id="s", organization_id="org_example")
    assert verify(key.public_key(), token).org == "org_example"
    body, signature = token.split(".")
    changed = mint(key, participant_id="p", scenario_id="s", organization_id="org_other").split(
        "."
    )[0]
    assert changed != body
    with pytest.raises(TokenError):
        verify(key.public_key(), f"{changed}.{signature}")


@pytest.mark.parametrize("organization", [42, True, "", "x" * 65])
def test_invalid_organization_claim_types_and_sizes_are_rejected(organization: Any) -> None:
    key = Ed25519PrivateKey.generate()
    token = mint(key, participant_id="p", scenario_id="s", organization_id=organization)
    with pytest.raises(TokenError):
        verify(key.public_key(), token)


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


def test_capability_round_trip_and_type_separation() -> None:
    key = Ed25519PrivateKey.generate()
    tok, claims = mint_capability(
        key,
        scenario_id="sc_1",
        investigation_id="inv_1",
        participant_id="p_e",
        action="reset_breaker",
        target="CB_C2_7",
    )
    assert verify_capability(key.public_key(), tok) == claims
    participant = mint(key, participant_id="p_e", scenario_id="sc_1")
    with pytest.raises(TokenError, match="not a capability"):
        verify_capability(key.public_key(), participant)
    with pytest.raises(TokenError, match="not a participant"):
        verify(key.public_key(), tok)


def test_capability_expires() -> None:
    key = Ed25519PrivateKey.generate()
    tok, _ = mint_capability(
        key,
        scenario_id="s",
        investigation_id="i",
        participant_id="p",
        action="a",
        target="t",
        ttl_s=300,
        now=1000,
    )
    with pytest.raises(TokenError, match="expired"):
        verify_capability(key.public_key(), tok, now=1301)


def test_a_fast_minting_clock_cannot_stretch_a_lifetime() -> None:
    key = Ed25519PrivateKey.generate()
    pub = key.public_key()
    cap, _ = mint_capability(
        key,
        scenario_id="s",
        investigation_id="i",
        participant_id="p",
        action="a",
        target="t",
        now=1000 + CLOCK_SKEW_S,
    )
    assert verify_capability(pub, cap, now=1000).sub == "p"  # within the skew allowance
    far, _ = mint_capability(
        key,
        scenario_id="s",
        investigation_id="i",
        participant_id="p",
        action="a",
        target="t",
        now=1000 + CLOCK_SKEW_S + 1,
    )
    with pytest.raises(TokenError, match="lifetime"):
        verify_capability(pub, far, now=1000)
    tok = mint(key, participant_id="p", scenario_id="s", now=1000 + 10 * 60)
    with pytest.raises(TokenError, match="lifetime"):
        verify(pub, tok, now=1000)


def test_lifetimes_cannot_be_requested_longer_than_the_maximum() -> None:
    key = Ed25519PrivateKey.generate()
    with pytest.raises(ValueError):
        mint_capability(
            key,
            scenario_id="s",
            investigation_id="i",
            participant_id="p",
            action="a",
            target="t",
            ttl_s=CAPABILITY_TTL_S + 1,
        )
    with pytest.raises(ValueError):
        mint(key, participant_id="p", scenario_id="s", ttl_s=PARTICIPANT_TTL_S + 1)
