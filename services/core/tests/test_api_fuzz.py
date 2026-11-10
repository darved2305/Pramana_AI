from __future__ import annotations

import json
import re
import uuid

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


def test_every_openapi_json_route_rejects_malformed_and_wrong_shape_inputs(
    core: TestClient,
) -> None:
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
    for method, template, _schema in operations:
        path = _concrete_path(template)
        for raw in payloads:
            response = core.request(
                method,
                path,
                content=raw,
                headers={
                    "Content-Type": "application/json",
                    "Idempotency-Key": "route-fuzz-key-0001",
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
