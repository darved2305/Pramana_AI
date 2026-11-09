"""Tamper-checked, organization- and filter-bound keyset cursors."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from typing import Any

from .errors import ApiError


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class CursorCodec:
    """Sign cursors with a domain-separated key derived from the participant signing secret."""

    def __init__(self, secret: str) -> None:
        self._key = hmac.new(
            secret.encode("utf-8"), b"pramana:list-cursor:v1", hashlib.sha256
        ).digest()

    @staticmethod
    def _filters(filters: dict[str, Any]) -> str:
        packed = json.dumps(
            filters, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(packed).hexdigest()

    def encode(
        self,
        *,
        scope: str,
        org_id: str,
        filters: dict[str, Any],
        sort: list[str | int],
    ) -> str:
        payload = json.dumps(
            {
                "v": 1,
                "scope": scope,
                "org": org_id,
                "filters": self._filters(filters),
                "sort": sort,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        body = _b64(payload)
        signature = _b64(hmac.new(self._key, body.encode("ascii"), hashlib.sha256).digest())
        return f"{body}.{signature}"

    def decode(
        self,
        value: str | None,
        *,
        scope: str,
        org_id: str,
        filters: dict[str, Any],
        sort_fields: int = 2,
    ) -> list[str | int] | None:
        if value is None:
            return None
        try:
            if len(value) > 4096:
                raise ValueError("cursor too large")
            body, signature = value.split(".", 1)
            expected = hmac.new(self._key, body.encode("ascii"), hashlib.sha256).digest()
            if not hmac.compare_digest(expected, _unb64(signature)):
                raise ValueError("invalid signature")
            payload = json.loads(_unb64(body))
            sort = payload["sort"]
            if (
                payload.get("v") != 1
                or payload.get("scope") != scope
                or payload.get("org") != org_id
                or payload.get("filters") != self._filters(filters)
                or not isinstance(sort, list)
                or len(sort) != sort_fields
                or any(not isinstance(part, (str, int)) for part in sort)
            ):
                raise ValueError("cursor context mismatch")
            return sort
        except (
            ValueError,
            KeyError,
            TypeError,
            UnicodeError,
            json.JSONDecodeError,
            binascii.Error,
        ):
            raise ApiError(
                400,
                "CURSOR_INVALID",
                "This page link is no longer valid. Restart from the first page.",
            ) from None
