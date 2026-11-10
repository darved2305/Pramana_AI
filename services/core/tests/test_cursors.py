"""Signed page cursors cannot cross collection, tenant, or filter boundaries."""

import pytest

from pramana_core.cursors import CursorCodec
from pramana_core.errors import ApiError


def test_cursor_round_trip_and_context_binding() -> None:
    codec = CursorCodec("test cursor signing secret")
    options = {"scope": "investigations", "org_id": "org-one", "filters": {"q": "wifi"}}
    cursor = codec.encode(**options, sort=["2026-11-09T00:00:00+00:00", "inv_1"])
    assert codec.decode(cursor, **options) == ["2026-11-09T00:00:00+00:00", "inv_1"]
    body, signature = cursor.split(".")
    tampered = body + "." + ("A" if signature[0] != "A" else "B") + signature[1:]
    for value, changed in (
        (tampered, options),
        (cursor, {**options, "scope": "sites"}),
        (cursor, {**options, "org_id": "org-two"}),
        (cursor, {**options, "filters": {"q": "water"}}),
    ):
        with pytest.raises(ApiError) as error:
            codec.decode(value, **changed)
        assert error.value.status == 400
        assert error.value.code == "CURSOR_INVALID"
