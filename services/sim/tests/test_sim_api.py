from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
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
        require_documented_models=False,  # Explicit legacy API compatibility coverage.
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
        require_documented_models=False,
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


PEOPLE_WITH_ELECTRICIAN = [
    *PEOPLE,
    {"id": "p_imran", "location_id": "MAINT_ROOM", "roles": ["electrician"]},
]


def electrician_scenario(client: TestClient, fault: Any = CB7) -> str:
    r = client.post(
        "/sim/v1/scenarios",
        headers=OPERATOR,
        json={
            "pack_id": "campus_block_c",
            "seed": 1,
            "participants": PEOPLE_WITH_ELECTRICIAN,
            "fault": fault,
        },
    )
    sid: str = r.json()["scenario_id"]
    return sid


def capability(
    sid: str, who: str = "p_imran", action: str = "reset_breaker", target: str = "CB_C2_7"
) -> str:
    from pramana_contracts.tokens import mint_capability

    tok, _ = mint_capability(
        KEY,
        scenario_id=sid,
        investigation_id="inv_1",
        participant_id=who,
        action=action,
        target=target,
    )
    return tok


def act(client: TestClient, sid: str, who: str, cap: str, target: str = "CB_C2_7") -> Any:
    return client.post(
        f"/sim/v1/scenarios/{sid}/act",
        headers=bearer(who, sid),
        json={"action": "reset_breaker", "target": target, "capability": cap},
    )


def test_approved_reset_changes_the_world_once(client: TestClient) -> None:
    sid = electrician_scenario(client)
    h = bearer("p_imran", sid)
    assert act(client, sid, "p_imran", capability(sid)).status_code == 409  # not at the panel
    client.post(f"/sim/v1/scenarios/{sid}/move", json={"to": "DB_C2_PANEL"}, headers=h)
    cap = capability(sid)
    r = act(client, sid, "p_imran", cap)
    assert r.json() == {"action": "reset_breaker", "target": "CB_C2_7", "performed": True}
    seen = client.post(
        f"/sim/v1/scenarios/{sid}/observe", json={"probe_id": "breaker_c2_7"}, headers=h
    ).json()
    assert seen["value"] == "up"
    assert act(client, sid, "p_imran", cap).status_code == 409  # single use


@pytest.mark.parametrize(
    ("who", "cap_for", "target", "status"),
    [
        ("p_mahesh", "p_mahesh", "CB_C2_7", 403),  # a guard is not an electrician
        ("p_imran", "p_mahesh", "CB_C2_7", 403),  # someone else's capability
        ("p_imran", "p_imran", "CB_C2_5", 403),
    ],  # capability covers another target
)
def test_capability_rules(
    client: TestClient, who: str, cap_for: str, target: str, status: int
) -> None:
    sid = electrician_scenario(client)
    for p in ("p_imran", "p_mahesh"):
        client.post(
            f"/sim/v1/scenarios/{sid}/move", json={"to": "DB_C2_PANEL"}, headers=bearer(p, sid)
        )
    assert act(client, sid, who, capability(sid, cap_for), target).status_code == status


def test_participant_token_is_not_a_capability(client: TestClient) -> None:
    sid = electrician_scenario(client)
    forged = bearer("p_imran", sid)["Authorization"].removeprefix("Bearer ")
    assert act(client, sid, "p_imran", forged).status_code == 403


def test_reset_response_does_not_reveal_whether_it_fixed_anything(client: TestClient) -> None:
    healthy = electrician_scenario(
        client, fault={"faults": [{"component_id": "SW_C2", "mode": "dead"}]}
    )
    tripped = electrician_scenario(client)
    bodies = []
    for sid in (healthy, tripped):
        client.post(
            f"/sim/v1/scenarios/{sid}/move",
            json={"to": "DB_C2_PANEL"},
            headers=bearer("p_imran", sid),
        )
        bodies.append(act(client, sid, "p_imran", capability(sid)).json())
    assert bodies[0] == bodies[1]


# -- sealed commitment, new probes, and repairs in a two-fault world -------------------------


def test_commitment_published_at_creation_is_the_one_revealed(client: TestClient) -> None:
    r = client.post(
        "/sim/v1/scenarios",
        headers=OPERATOR,
        json={"pack_id": "campus_block_c", "seed": 3, "participants": PEOPLE, "fault": CB7},
    )
    created = r.json()
    assert set(created) >= {"scenario_id", "commitment"}
    assert "salt" not in r.text
    assert "CB_C2_7" not in r.text
    sid = created["scenario_id"]
    client.post(f"/sim/v1/scenarios/{sid}/close", headers=OPERATOR)
    reveal = client.post(f"/sim/v1/scenarios/{sid}/reveal", headers=OPERATOR).json()
    assert reveal["commitment"] == created["commitment"]
    recomputed = commitment_for(sid, FaultSpec.model_validate(reveal["fault_spec"]), reveal["salt"])
    assert recomputed == created["commitment"]
    # A different claimed fault, or the right fault with another salt, does not match.
    other = FaultSpec.model_validate({"faults": [{"component_id": "SW_C2", "mode": "dead"}]})
    assert commitment_for(sid, other, reveal["salt"]) != created["commitment"]
    assert commitment_for(sid, FaultSpec.model_validate(CB7), "x") != created["commitment"]


def test_commitment_does_not_depend_on_fault_order() -> None:
    a = {"component_id": "ISP_LINK", "mode": "down"}
    b = {"component_id": "AP_3B", "mode": "dead"}
    one = commitment_for("sc", FaultSpec.model_validate({"faults": [a, b]}), "s")
    two = commitment_for("sc", FaultSpec.model_validate({"faults": [b, a]}), "s")
    assert one == two


def test_views_include_the_socket_breaker_and_fibre_probes(client: TestClient) -> None:
    feed = {"faults": [{"component_id": "FEED_C2", "mode": "lost"}]}
    sid = electrician_scenario(client, fault=feed)
    riya = client.get(f"/sim/v1/scenarios/{sid}/view", headers=bearer("p_riya", sid)).json()
    assert {i["probe_id"]: i["value"] for i in riya["items"]}["room_socket"] == "off"
    h = bearer("p_imran", sid)
    client.post(f"/sim/v1/scenarios/{sid}/move", json={"to": "DB_C2_PANEL"}, headers=h)
    panel = client.get(f"/sim/v1/scenarios/{sid}/view", headers=h).json()
    values = {i["probe_id"]: i["value"] for i in panel["items"]}
    assert values["breaker_c2_7"] == "up"
    assert values["breaker_c2_5"] == "up"  # lost supply: nothing tripped at the panel
    g = bearer("p_mahesh", sid)
    assert (
        client.post(f"/sim/v1/scenarios/{sid}/move", json={"to": "IDF1"}, headers=g).status_code
        == 200
    )
    rack = client.get(f"/sim/v1/scenarios/{sid}/view", headers=g).json()
    rack_values = {i["probe_id"]: i["value"] for i in rack["items"]}
    assert rack_values["fibre_light"] == "green"
    assert "breaker_main_1" not in rack_values  # a guard does not read electrical panels


def test_repair_in_a_two_fault_world_clears_only_its_own_fault(client: TestClient) -> None:
    two = {
        "faults": [
            {"component_id": "CB_C2_7", "mode": "tripped"},
            {"component_id": "ISP_LINK", "mode": "down"},
        ]
    }
    sid = electrician_scenario(client, fault=two)
    h = bearer("p_imran", sid)
    client.post(f"/sim/v1/scenarios/{sid}/move", json={"to": "DB_C2_PANEL"}, headers=h)
    assert act(client, sid, "p_imran", capability(sid)).status_code == 200
    riya = client.get(f"/sim/v1/scenarios/{sid}/view", headers=bearer("p_riya", sid)).json()
    values = {i["probe_id"]: i["value"] for i in riya["items"]}
    assert values["wifi_status"] == "connected"  # power is back on floor 3's switch
    assert values["web_by_ip"] == "no"  # but the provider link is still down
    client.post(f"/sim/v1/scenarios/{sid}/close", headers=OPERATOR)
    reveal = client.post(f"/sim/v1/scenarios/{sid}/reveal", headers=OPERATOR).json()
    assert reveal["commitment_verified"] is True  # the seal is of the original faults
    assert len(reveal["fault_spec"]["faults"]) == 2


# -- presence tokens (S7) -----------------------------------------------------------------------


def _check(client: TestClient, sid: str, answer: str, pid: str = "p_mahesh", **kw: Any) -> Any:
    body = {"participant_id": pid, "token_id": "idf2_switch_label", "answer": answer}
    return client.post(f"/sim/v1/scenarios/{sid}/presence/check", json=body, **kw)


def _label(client: TestClient, sid: str) -> str:
    h = bearer("p_mahesh", sid)
    client.post(f"/sim/v1/scenarios/{sid}/move", json={"to": "IDF2"}, headers=h)
    view = client.get(f"/sim/v1/scenarios/{sid}/view", headers=h).json()
    (label,) = view["labels"]
    assert label["token_id"] == "idf2_switch_label"
    value: str = label["value"]
    return value


def test_presence_label_is_shown_only_on_site(client: TestClient) -> None:
    sid = scenario(client, CB7)
    h = bearer("p_mahesh", sid)
    assert client.get(f"/sim/v1/scenarios/{sid}/view", headers=h).json()["labels"] == []
    value = _label(client, sid)
    assert len(value) == 3
    assert set(value) <= set("AFHKLMQRXY345679")


def test_presence_check_never_discloses_the_value(client: TestClient) -> None:
    sid = scenario(client, CB7)
    value = _label(client, sid)
    r = _check(client, sid, "zzz", headers=OPERATOR)
    assert r.status_code == 200
    assert r.json() == {"passed": False, "attempts_left": 1}
    assert value not in r.text
    r = _check(client, sid, f" {value[0]} {value[1].lower()}-{value[2]}. ", headers=OPERATOR)
    assert r.json() == {"passed": True, "attempts_left": 0}


def test_presence_check_is_limited_and_needs_the_operator_key(client: TestClient) -> None:
    sid = scenario(client, CB7)
    value = _label(client, sid)
    assert _check(client, sid, value).status_code == 401
    assert _check(client, sid, value, headers=bearer("p_mahesh", sid)).status_code == 401
    _check(client, sid, "AAA", headers=OPERATOR)
    _check(client, sid, "AAA", headers=OPERATOR)
    # Two tries are used up: even the right reading no longer passes (no brute force).
    assert _check(client, sid, value, headers=OPERATOR).json() == {
        "passed": False,
        "attempts_left": 0,
    }


def test_presence_check_rejects_unknown_tokens_people_and_empty_readings(
    client: TestClient,
) -> None:
    sid = scenario(client, CB7)
    body = {"participant_id": "p_mahesh", "token_id": "nope", "answer": "AAA"}
    r = client.post(f"/sim/v1/scenarios/{sid}/presence/check", json=body, headers=OPERATOR)
    assert r.status_code == 422
    assert _check(client, sid, "AAA", pid="p_nobody", headers=OPERATOR).status_code == 403
    assert _check(client, sid, "  -- ", headers=OPERATOR).json()["passed"] is False


def test_presence_values_are_fresh_per_scenario(client: TestClient) -> None:
    values = {_label(client, scenario(client, CB7)) for _ in range(12)}
    assert len(values) > 1
    from pramana_sim.scenario import PRESENCE_ALPHABET

    assert all(set(v) <= set(PRESENCE_ALPHABET) for v in values)


def _persistent_settings(state_file: Path) -> SimSettings:
    return SimSettings(
        operator_key=SecretStr("op-secret"),
        require_documented_models=False,
        oracle_key=SecretStr("oracle-secret"),
        participant_public_key=public_key_b64(KEY),
        state_file=str(state_file),
    )


def test_repaired_world_and_used_capability_survive_simulator_restart(tmp_path: Path) -> None:
    state_file = tmp_path / "scenarios.json"
    settings = _persistent_settings(state_file)
    with TestClient(create_app(settings)) as first:
        sid = electrician_scenario(first)
        electrician = bearer("p_imran", sid)
        assert (
            first.post(
                f"/sim/v1/scenarios/{sid}/move", json={"to": "DB_C2_PANEL"}, headers=electrician
            ).status_code
            == 200
        )
        cap = capability(sid)
        assert act(first, sid, "p_imran", cap).status_code == 200

    snapshot = json.loads(state_file.read_text(encoding="utf-8"))
    saved = snapshot["scenarios"][0]
    assert saved["active_faults"] == []
    assert len(saved["used_capabilities"]) == 1
    assert saved["interventions"] == [["p_imran", "reset_breaker", "CB_C2_7"]]

    with TestClient(create_app(settings)) as restarted:
        view = restarted.get(f"/sim/v1/scenarios/{sid}/view", headers=bearer("p_imran", sid))
        assert view.json()["location_id"] == "DB_C2_PANEL"
        seen = restarted.post(
            f"/sim/v1/scenarios/{sid}/observe",
            json={"probe_id": "breaker_c2_7"},
            headers=bearer("p_imran", sid),
        )
        assert seen.json()["value"] == "up"
        replay = act(restarted, sid, "p_imran", cap)
        assert replay.status_code == 409
        assert replay.json()["error"]["code"] == "CAPABILITY_USED"


def test_presence_value_and_attempt_limit_survive_simulator_restart(tmp_path: Path) -> None:
    settings = _persistent_settings(tmp_path / "scenarios.json")
    with TestClient(create_app(settings)) as first:
        sid = scenario(first, CB7)
        value = _label(first, sid)
        failed = _check(first, sid, "AAA", headers=OPERATOR)
        assert failed.json() == {"passed": False, "attempts_left": 1}

    with TestClient(create_app(settings)) as restarted:
        assert _label(restarted, sid) == value
        passed = _check(restarted, sid, value, headers=OPERATOR)
        assert passed.json() == {"passed": True, "attempts_left": 0}


def test_closed_scenario_stays_closed_and_revealable_after_restart(tmp_path: Path) -> None:
    settings = _persistent_settings(tmp_path / "scenarios.json")
    with TestClient(create_app(settings)) as first:
        sid = scenario(first, CB7)
        commitment = first.post(f"/sim/v1/scenarios/{sid}/close", headers=OPERATOR).status_code
        assert commitment == 204

    with TestClient(create_app(settings)) as restarted:
        view = restarted.get(f"/sim/v1/scenarios/{sid}/view", headers=bearer("p_riya", sid))
        assert view.status_code == 409
        assert view.json()["error"]["code"] == "SCENARIO_CLOSED"
        reveal = restarted.post(f"/sim/v1/scenarios/{sid}/reveal", headers=OPERATOR)
        assert reveal.status_code == 200
        assert reveal.json()["fault_spec"] == CB7
        assert reveal.json()["commitment_verified"] is True


def test_invalid_snapshot_fails_simulator_startup_closed(tmp_path: Path) -> None:
    state_file = tmp_path / "scenarios.json"
    state_file.write_text("not valid json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="state file could not be loaded"):
        create_app(_persistent_settings(state_file))


def test_legacy_snapshot_without_presence_state_migrates_on_load(tmp_path: Path) -> None:
    state_file = tmp_path / "scenarios.json"
    settings = _persistent_settings(state_file)
    with TestClient(create_app(settings)) as first:
        sid = scenario(first, CB7)
        _label(first, sid)

    snapshot = json.loads(state_file.read_text(encoding="utf-8"))
    snapshot["version"] = 1
    snapshot["scenarios"][0].pop("presence_values")
    snapshot["scenarios"][0].pop("presence_attempts")
    state_file.write_text(json.dumps(snapshot), encoding="utf-8")

    with TestClient(create_app(settings)) as restarted:
        view = restarted.get(f"/sim/v1/scenarios/{sid}/view", headers=bearer("p_mahesh", sid))
        assert view.status_code == 200
        assert view.json()["location_id"] == "IDF2"
        (label,) = view.json()["labels"]
        assert label["token_id"] == "idf2_switch_label"
        assert len(label["value"]) == 3


def test_failed_snapshot_write_rolls_back_participant_move(tmp_path: Path) -> None:
    state_file = tmp_path / "scenarios.json"
    settings = _persistent_settings(state_file)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        sid = scenario(client, CB7)
        state_file.unlink()
        state_file.mkdir()

        moved = client.post(
            f"/sim/v1/scenarios/{sid}/move",
            json={"to": "IDF2"},
            headers=bearer("p_mahesh", sid),
        )
        assert moved.status_code == 500
        restored = client.get(f"/sim/v1/scenarios/{sid}/view", headers=bearer("p_mahesh", sid))
        assert restored.status_code == 200
        assert restored.json()["location_id"] == "GUARD_DESK"
        assert list(tmp_path.glob("scenarios.json.*.tmp")) == []
