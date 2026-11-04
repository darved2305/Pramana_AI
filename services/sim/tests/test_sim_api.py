from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from pydantic import SecretStr

from pramana_contracts import FaultSpec
from pramana_contracts.tokens import mint, public_key_b64
from pramana_domain import load_pack
from pramana_sim.app import SimSettings, create_app
from pramana_sim.scenario import commitment_for, draw_fault

OPERATOR = {"X-Operator-Key": "op-secret"}
ORACLE = {"X-Oracle-Key": "oracle-secret"}
KEY = Ed25519PrivateKey.generate()

PEOPLE = [
    {"id": "p_riya", "location_id": "F3_R304", "roles": ["student"]},
    {"id": "p_mahesh", "location_id": "GUARD_DESK", "roles": ["guard"]},
]


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = SimSettings(
        operator_key=SecretStr("op-secret"),
        oracle_key=SecretStr("oracle-secret"),
        participant_public_key=public_key_b64(KEY),
    )
    with TestClient(create_app(settings)) as c:
        yield c


def scenario(client: TestClient, fault: Any = None, seed: int = 1) -> str:
    body = {
        "pack_id": "campus_block_c",
        "seed": seed,
        "participants": PEOPLE,
        "fault": fault if fault is not None else "random",
    }
    r = client.post("/sim/v1/scenarios", json=body, headers=OPERATOR)
    assert r.status_code == 201, r.text
    sid: str = r.json()["scenario_id"]
    return sid


def bearer(pid: str, sid: str, key: Ed25519PrivateKey = KEY, **kw: Any) -> dict[str, str]:
    return {"Authorization": "Bearer " + mint(key, participant_id=pid, scenario_id=sid, **kw)}


CB7 = {"faults": [{"component_id": "CB_C2_7", "mode": "tripped"}]}


def test_creation_requires_operator_key(client: TestClient) -> None:
    body = {"pack_id": "campus_block_c", "seed": 1, "participants": PEOPLE}
    assert client.post("/sim/v1/scenarios", json=body).status_code == 401
    bad = {"X-Operator-Key": "guess"}
    assert client.post("/sim/v1/scenarios", json=body, headers=bad).status_code == 401


def test_creation_response_does_not_leak_the_fault(client: TestClient) -> None:
    r = client.post(
        "/sim/v1/scenarios",
        headers=OPERATOR,
        json={"pack_id": "campus_block_c", "seed": 1, "participants": PEOPLE, "fault": CB7},
    )
    assert set(r.json()) == {"scenario_id", "commitment"}
    assert "CB_C2_7" not in r.text


def test_unknown_fault_and_pack_are_rejected(client: TestClient) -> None:
    body = {
        "pack_id": "campus_block_c",
        "seed": 1,
        "participants": PEOPLE,
        "fault": {"faults": [{"component_id": "SW_C2", "mode": "melted"}]},
    }
    assert client.post("/sim/v1/scenarios", json=body, headers=OPERATOR).status_code == 422
    body = {"pack_id": "nope", "seed": 1, "participants": PEOPLE}
    r = client.post("/sim/v1/scenarios", json=body, headers=OPERATOR)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNKNOWN_PACK"


def test_view_shows_what_the_participant_can_perceive(client: TestClient) -> None:
    sid = scenario(client, CB7)
    view = client.get(f"/sim/v1/scenarios/{sid}/view", headers=bearer("p_riya", sid)).json()
    values = {i["probe_id"]: i["value"] for i in view["items"]}
    assert view["location_id"] == "F3_R304"
    assert values["wifi_status"] == "no_network"
    assert values["corridor_lights"] == "on"
    assert "nvr_screen" not in values  # not visible from a student's room
    assert view["reachable_locations"] == []  # students are not asked to walk


def test_tokens_are_verified_and_scoped(client: TestClient) -> None:
    sid = scenario(client, CB7)
    other = scenario(client, CB7)
    url = f"/sim/v1/scenarios/{sid}/view"
    assert client.get(url).status_code == 401
    assert (
        client.get(url, headers=bearer("p_riya", sid, Ed25519PrivateKey.generate())).status_code
        == 401
    )
    assert client.get(url, headers=bearer("p_riya", other)).status_code == 403
    assert client.get(url, headers=bearer("p_riya", sid, ttl_s=-10)).status_code == 401
    assert client.get(url, headers=bearer("p_riya", sid, aud="core")).status_code == 401
    assert client.get(url, headers=bearer("p_ghost", sid)).status_code == 403


def test_guard_walks_to_closet_and_reads_the_recorder(client: TestClient) -> None:
    sid = scenario(client, CB7)
    h = bearer("p_mahesh", sid)
    r = client.post(f"/sim/v1/scenarios/{sid}/move", json={"to": "IDF2"}, headers=h)
    assert r.json() == {"location_id": "IDF2", "walk_s": 65}
    r = client.post(f"/sim/v1/scenarios/{sid}/observe", json={"probe_id": "nvr_screen"}, headers=h)
    assert r.json() == {"probe_id": "nvr_screen", "location_id": "IDF2", "value": "off"}


def test_access_and_role_rules_are_enforced(client: TestClient) -> None:
    sid = scenario(client, CB7)
    riya, mahesh = bearer("p_riya", sid), bearer("p_mahesh", sid)
    r = client.post(f"/sim/v1/scenarios/{sid}/move", json={"to": "IDF2"}, headers=riya)
    assert r.status_code == 403
    client.post(f"/sim/v1/scenarios/{sid}/move", json={"to": "DB_C2_PANEL"}, headers=mahesh)
    r = client.post(
        f"/sim/v1/scenarios/{sid}/observe", json={"probe_id": "breaker_c2_7"}, headers=mahesh
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ROLE_NOT_PERMITTED"
    r = client.post(
        f"/sim/v1/scenarios/{sid}/observe", json={"probe_id": "nvr_screen"}, headers=mahesh
    )
    assert r.status_code == 409


def test_truth_requires_the_oracle_key(client: TestClient) -> None:
    sid = scenario(client, CB7)
    url = f"/sim/v1/scenarios/{sid}/truth"
    assert client.get(url).status_code == 403
    assert client.get(url, headers=OPERATOR).status_code == 403  # the core's key is not enough
    assert client.get(url, headers=bearer("p_riya", sid)).status_code == 403
    assert client.get(url, headers=ORACLE).json() == {
        "faults": [{"component_id": "CB_C2_7", "mode": "tripped"}]
    }


def test_truth_route_is_disabled_without_an_oracle_key() -> None:
    settings = SimSettings(  # explicit None: a developer's .env must not leak into tests
        operator_key=SecretStr("op-secret"),
        oracle_key=None,
        participant_public_key=public_key_b64(KEY),
    )
    with TestClient(create_app(settings)) as c:
        sid = scenario(c, CB7)
        assert c.get(f"/sim/v1/scenarios/{sid}/truth", headers=ORACLE).status_code == 404


def test_reveal_only_after_close_and_close_ends_observation(client: TestClient) -> None:
    sid = scenario(client, CB7)
    created_commitment = None
    r = client.post(f"/sim/v1/scenarios/{sid}/reveal", headers=OPERATOR)
    assert r.status_code == 409
    view_url = f"/sim/v1/scenarios/{sid}/view"
    assert client.get(view_url, headers=bearer("p_riya", sid)).status_code == 200
    assert client.post(f"/sim/v1/scenarios/{sid}/close").status_code == 401
    assert client.post(f"/sim/v1/scenarios/{sid}/close", headers=OPERATOR).status_code == 204
    assert client.get(view_url, headers=bearer("p_riya", sid)).status_code == 409
    reveal = client.post(f"/sim/v1/scenarios/{sid}/reveal", headers=OPERATOR).json()
    assert reveal["fault_spec"] == CB7
    assert reveal["commitment_verified"] is True
    created_commitment = commitment_for(sid, FaultSpec.model_validate(CB7), reveal["salt"])
    assert reveal["commitment"] == created_commitment


def test_commitment_binds_the_fault() -> None:
    a = commitment_for("sc_1", FaultSpec.model_validate(CB7), "salt")
    b = commitment_for(
        "sc_1",
        FaultSpec.model_validate({"faults": [{"component_id": "SW_C2", "mode": "dead"}]}),
        "salt",
    )
    c = commitment_for("sc_1", FaultSpec.model_validate(CB7), "salt2")
    assert len({a, b, c}) == 3


def test_random_faults_are_seeded_and_cover_the_catalogue() -> None:
    pack = load_pack("campus_block_c")
    assert draw_fault(pack, 42) == draw_fault(pack, 42)
    seen = {tuple((f.component_id, f.mode) for f in draw_fault(pack, s).faults) for s in range(400)}
    assert len(seen) >= 10
    assert () in seen  # "nothing broken" is a possible draw


def test_multiple_fault_scenarios_are_supported(client: TestClient) -> None:
    two = {
        "faults": [
            {"component_id": "ISP_LINK", "mode": "down"},
            {"component_id": "AP_3B", "mode": "dead"},
        ]
    }
    sid = scenario(client, two)
    view = client.get(f"/sim/v1/scenarios/{sid}/view", headers=bearer("p_riya", sid)).json()
    values = {i["probe_id"]: i["value"] for i in view["items"]}
    assert values["wifi_status"] == "connected"
    assert values["web_by_ip"] == "no"
