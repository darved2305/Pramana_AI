"""Stable bytes for a documented site's stored specification, independent of file paths."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .pack import DomainPack


def canonical_spec(spec: dict[str, Any]) -> bytes:
    return json.dumps(
        spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def spec_digest(spec: dict[str, Any]) -> bytes:
    return hashlib.sha256(canonical_spec(spec)).digest()


def load_spec(spec: dict[str, Any]) -> DomainPack:
    """Read both stored field names and the pack format's aliases without rewriting bytes.

    The first frozen template uses ``model_dump`` field names (hi_en/probe_class). Existing
    stored hashes and immutable versions stay intact; YAML aliases are accepted too. Duplicate
    alias/name inputs still fail the model's extra-field checks.
    """
    return DomainPack.model_validate(spec, by_alias=True, by_name=True)
