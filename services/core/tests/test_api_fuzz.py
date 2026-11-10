from __future__ import annotations

import json
import re
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pramana_core import ids

pytestmark = pytest.mark.db


def _core_json_operations(client: TestClient) -> list[tuple[str, str, dict[str, object]]]:
    operations = []
    for path, methods in client.app.openapi()["paths"].items():
        for method, operation in methods.items():
            if not isinstance(operation, dict):
                continue
            content = operation.get("requestBody", {}).get("content", {})
            if "application/json" in content:
                operations.append((method.upper(), path, content["application/json"]["schema"]))
    return operations


def _concrete_path(path: str) -> str:
    values = {
        "org": "pramana-demo",
        "domain": "fuzz.invalid",
        "site_id": ids.new("site")[1],
        "model_id": ids.new("model")[1],
        "inv_id": ids.new("inv")[1],
        "approval_id": str(uuid.uuid4()),
        "member_id": ids.new("mem")[1],
        "person_id": "p_fuzz",
        "participant_id": "p_fuzz",
        "request_id": ids.new("join")[1],
        "code": "invalid-fuzz-code",
    }
    return re.sub(r"\{([a-z_]+)\}", lambda match: values[match.group(1)], path)


def _resolved_schema(openapi: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    result = dict(schema)
    seen: set[str] = set()
    while isinstance(result.get("$ref"), str):
        ref = result["$ref"]
        if ref in seen or not ref.startswith("#/components/schemas/"):
            break
        seen.add(ref)
        name = ref.rsplit("/", 1)[1].replace("~1", "/").replace("~0", "~")
        target = openapi.get("components", {}).get("schemas", {}).get(name)
        if not isinstance(target, dict):
            break
        result = {**target, **{key: value for key, value in result.items() if key != "$ref"}}

    all_of = result.get("allOf")
    if isinstance(all_of, list):
        merged: dict[str, Any] = {}
        for variant in all_of:
            if isinstance(variant, dict):
                resolved = _resolved_schema(openapi, variant)
                merged.update(resolved)
        merged.update({key: value for key, value in result.items() if key != "allOf"})
        result = merged
    return result


def _schema_types(openapi: dict[str, Any], schema: dict[str, Any]) -> set[str]:
    resolved = _resolved_schema(openapi, schema)
    found: set[str] = set()
    schema_type = resolved.get("type")
    if isinstance(schema_type, str):
        found.add(schema_type)
    if isinstance(resolved.get("properties"), dict):
        found.add("object")
    if isinstance(resolved.get("items"), dict):
        found.add("array")
    for key in ("anyOf", "oneOf", "allOf"):
        variants = resolved.get(key)
        if isinstance(variants, list):
            for variant in variants:
                if isinstance(variant, dict):
                    found.update(_schema_types(openapi, variant))
    return found


def _wrong_json_value(openapi: dict[str, Any], schema: dict[str, Any]) -> Any:
    valid_types = _schema_types(openapi, schema)
    candidates = (
        {"fuzz": "invalid-object"},
        [],
        "invalid-fuzz-value",
        0,
        True,
        None,
    )
    for value in candidates:
        if value is None:
            candidate_type = "null"
        elif isinstance(value, dict):
            candidate_type = "object"
        elif isinstance(value, list):
            candidate_type = "array"
        elif isinstance(value, bool):
            candidate_type = "boolean"
        elif isinstance(value, int):
            candidate_type = "integer"
        else:
            candidate_type = "string"
        if candidate_type not in valid_types and not (
            candidate_type == "integer" and "number" in valid_types
        ):
            return value
    return {"fuzz": "invalid-value"}


def _schema_invalid_payload(openapi: dict[str, Any], schema: dict[str, Any]) -> Any:
    resolved = _resolved_schema(openapi, schema)
    properties = resolved.get("properties")
    if not isinstance(properties, dict) or not properties:
        return _wrong_json_value(openapi, schema)
    required = resolved.get("required")
    candidates = required if isinstance(required, list) else []
    field = next((name for name in candidates if name in properties), next(iter(properties)))
    field_schema = properties[field]
    if not isinstance(field_schema, dict):
        return {field: {"fuzz": "invalid-schema"}}
    return {field: _wrong_json_value(openapi, field_schema)}


def test_every_openapi_json_route_rejects_malformed_and_wrong_shape_inputs(
    core: TestClient,
) -> None:
    openapi = core.app.openapi()
    operations = _core_json_operations(core)
    assert len(operations) >= 30
    payloads = (
        b"{",
        b"[]",
        b'"wrong top-level type"',
        b"{}",
        b'{"seed":"not-a-number","limit":-9223372036854775808}',
        json.dumps({"value": "ગુજરાતી 🌦️ " + ("x" * 10_000)}, ensure_ascii=False).encode(),
    )
    for method, template, schema in operations:
        path = _concrete_path(template)
        schema_payload = json.dumps(
            _schema_invalid_payload(openapi, schema), ensure_ascii=False
        ).encode()
        for raw in (*payloads, schema_payload):
            response = core.request(
                method,
                path,
                content=raw,
                headers={
                    "Content-Type": "application/json",
                    "Idempotency-Key": uuid.uuid4().hex,
                },
            )
            assert response.status_code < 500, (
                method,
                template,
                response.status_code,
                response.text,
            )
            assert "Traceback" not in response.text
            assert 'File "' not in response.text
            if response.status_code >= 400:
                body = response.json()
                assert set(body) == {"error"}, (method, template, body)
                assert {"code", "message", "request_id"} <= set(body["error"])
