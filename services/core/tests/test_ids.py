"""UUIDv7 ids and their type-prefixed public form (ADR 0015)."""

from __future__ import annotations

import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pramana_core import ids


def test_uuid7_has_version_and_variant() -> None:
    u = ids.uuid7()
    assert u.version == 7
    assert u.variant == uuid.RFC_4122


def test_uuid7_orders_by_time() -> None:
    earlier = ids.uuid7(now_ms=1_700_000_000_000)
    later = ids.uuid7(now_ms=1_700_000_000_001)
    assert earlier < later
    assert earlier.int >> 80 == 1_700_000_000_000


def test_uuid7_is_random_within_a_millisecond() -> None:
    assert len({ids.uuid7(now_ms=5) for _ in range(1000)}) == 1000


@given(st.uuids())
def test_public_id_round_trips(u: uuid.UUID) -> None:
    public = ids.encode("org", u)
    assert public.startswith("org_")
    assert len(public) == 30
    assert ids.decode("org", public) == u


def test_prefix_is_checked() -> None:
    _, public = ids.new("inv")
    with pytest.raises(ValueError):
        ids.decode("org", public)


@pytest.mark.parametrize(
    "bad",
    ["org_", "org", "org_0000000000000000000000000U", "org_" + "Z" * 26, "orgX" + "0" * 26],
)
def test_malformed_ids_are_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        ids.decode("org", bad)


def test_unknown_prefix_is_rejected() -> None:
    with pytest.raises(ValueError):
        ids.encode("user", ids.uuid7())
