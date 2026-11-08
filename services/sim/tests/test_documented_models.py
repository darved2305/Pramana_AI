"""Saved physical models remain distinct through simulation, recovery and failed writes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from pydantic import SecretStr

from pramana_contracts.tokens import mint, public_key_b64
from pramana_domain import load_pack
from pramana_domain.spec_storage import spec_digest
from pramana_sim.app import SimSettings, create_app

KEY = Ed25519PrivateKey.generate()
OPERATOR = {"X-Operator-Key": "documented-model-test"}
CB7 = {"faults": [{"component_id": "CB_C2_7", "mode": "tripped"}]}
PEOPLE = [
    {"id": "p_riya", "location_id": "F3_R304", "roles": ["student"]},
    {"id": "p_mahesh", "location_id": "GUARD_DESK", "roles": ["guard"]},
]


def _persistent_settings(path: Path) -> SimSettings:
    return SimSettings(
        operator_key=SecretStr(OPERATOR["X-Operator-Key"]),
        participant_public_key=public_key_b64(KEY),
        state_file=str(path),
        oracle_key=None,
    )


def bearer(participant: str, scenario: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer " + mint(KEY, participant_id=participant, scenario_id=scenario)
    }


def document(*, changed: bool = False) -> dict[str, Any]:
    spec = load_pack("campus_block_c").model_dump(mode="json")
    if changed:
        for component in spec["components"]:
            if component["id"] in ("AP_3A", "AP_3B"):
                component["poe_from"] = "SW_CORE"
    return {"spec": spec, "sha256": spec_digest(spec).hex()}


def request(model: dict[str, Any]) -> dict[str, Any]:
    return {
        "pack_id": "campus_block_c",
        "seed": 7,
        "fault": CB7,
        "participants": PEOPLE,
        "documented_model": model,
    }


def no_files(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("documented scenarios must not load a pack file")


def test_two_same_label_physical_models_survive_restart_without_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _persistent_settings(tmp_path / "scenarios.json").model_copy(
        update={"require_documented_models": True}
    )
    models = [document(), document(changed=True)]
    monkeypatch.setattr("pramana_sim.app.load_pack", no_files)
    with TestClient(create_app(settings)) as client:
        scenarios = []
        for model in models:
            response = client.post("/sim/v1/scenarios", json=request(model), headers=OPERATOR)
            assert response.status_code == 201, response.text
            assert set(response.json()) == {"scenario_id", "commitment"}
            scenarios.append(response.json()["scenario_id"])
    snapshot = json.loads((tmp_path / "scenarios.json").read_text(encoding="utf-8"))
    assert snapshot["version"] == 3
    assert [s["documented_model"]["sha256"] for s in snapshot["scenarios"]] == [
        model["sha256"] for model in models
    ]
    with TestClient(create_app(settings)) as restarted:
        values = []
        for sid in scenarios:
            response = restarted.post(
                f"/sim/v1/scenarios/{sid}/observe",
                json={"probe_id": "wifi_status"},
                headers=bearer("p_riya", sid),
            )
            assert response.status_code == 200, response.text
            values.append(response.json()["value"])
        assert values == ["no_network", "connected"]


@pytest.mark.parametrize("failure", ["hash", "schema", "label"])
def test_inconsistent_documented_model_is_rejected(tmp_path: Path, failure: str) -> None:
    model = document()
    if failure == "hash":
        model["sha256"] = "0" * 64
    elif failure == "schema":
        model["spec"]["components"] = []
        model["sha256"] = spec_digest(model["spec"]).hex()
    else:
        model["spec"]["pack"] = "another_label"
        model["sha256"] = spec_digest(model["spec"]).hex()
    with TestClient(create_app(_persistent_settings(tmp_path / "state.json"))) as client:
        response = client.post("/sim/v1/scenarios", json=request(model), headers=OPERATOR)
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "INVALID_MODEL"
        # Model input is operator-only, even when the payload is valid.
        assert client.post("/sim/v1/scenarios", json=request(document())).status_code == 401


def test_required_model_never_falls_back_to_a_named_pack(tmp_path: Path) -> None:
    settings = _persistent_settings(tmp_path / "state.json").model_copy(
        update={"require_documented_models": True}
    )
    body = request(document())
    body.pop("documented_model")
    with TestClient(create_app(settings)) as client:
        response = client.post("/sim/v1/scenarios", json=body, headers=OPERATOR)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "MODEL_REQUIRED"


def test_documented_world_rolls_back_failed_move_without_loading_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "state.json"
    payload = request(document(changed=True))
    monkeypatch.setattr("pramana_sim.app.load_pack", no_files)
    with TestClient(
        create_app(_persistent_settings(path)), raise_server_exceptions=False
    ) as client:
        response = client.post("/sim/v1/scenarios", json=payload, headers=OPERATOR)
        assert response.status_code == 201, response.text
        sid = response.json()["scenario_id"]
        path.unlink()
        path.mkdir()
        moved = client.post(
            f"/sim/v1/scenarios/{sid}/move", json={"to": "IDF2"}, headers=bearer("p_mahesh", sid)
        )
        assert moved.status_code == 500
        view = client.get(f"/sim/v1/scenarios/{sid}/view", headers=bearer("p_mahesh", sid))
        assert view.json()["location_id"] == "GUARD_DESK"
        observed = client.post(
            f"/sim/v1/scenarios/{sid}/observe",
            json={"probe_id": "wifi_status"},
            headers=bearer("p_riya", sid),
        )
        assert observed.json()["value"] == "connected"


@pytest.mark.parametrize("failure", ["missing", "changed"])
def test_v3_snapshot_with_missing_or_changed_model_fails_closed(
    tmp_path: Path, failure: str
) -> None:
    path = tmp_path / "state.json"
    settings = _persistent_settings(path)
    with TestClient(create_app(settings)) as client:
        assert (
            client.post("/sim/v1/scenarios", json=request(document()), headers=OPERATOR).status_code
            == 201
        )
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if failure == "missing":
        snapshot["scenarios"][0].pop("documented_model")
    else:
        snapshot["scenarios"][0]["documented_model"]["spec"]["title"] = "changed"
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    with pytest.raises(RuntimeError, match="state file could not be loaded"):
        create_app(settings)


def test_v2_snapshot_without_a_documented_model_is_explicitly_supported(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    settings = _persistent_settings(path)
    with TestClient(create_app(settings)) as client:
        response = client.post("/sim/v1/scenarios", json=request(document()), headers=OPERATOR)
        assert response.status_code == 201
        sid = response.json()["scenario_id"]
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    snapshot["version"] = 2
    snapshot["scenarios"][0].pop("documented_model")
    path.write_text(json.dumps(snapshot), encoding="utf-8")
    with TestClient(create_app(settings)) as restarted:
        view = restarted.get(f"/sim/v1/scenarios/{sid}/view", headers=bearer("p_riya", sid))
        assert view.status_code == 200
