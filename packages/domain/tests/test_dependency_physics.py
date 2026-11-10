"""Sites described as a dependency graph: any system with parts that depend on other parts."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from pramana_domain import DomainPack, World, load_pack, predict
from pramana_domain.pack import default_packs_dir

WATER = default_packs_dir() / "templates" / "building_water_supply.yaml"


@pytest.fixture(scope="module")
def raw() -> dict[str, Any]:
    with WATER.open(encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh)
    return data


@pytest.fixture(scope="module")
def water() -> DomainPack:
    return load_pack(WATER)


def _invalid(raw: dict[str, Any], mutate: Any, match: str) -> None:
    data = copy.deepcopy(raw)
    mutate(data)
    with pytest.raises(ValidationError, match=match):
        DomainPack.model_validate(data)


def _component(d: dict[str, Any], cid: str) -> dict[str, Any]:
    return next(c for c in d["components"] if c["id"] == cid)


def _probe(d: dict[str, Any], pid: str) -> dict[str, Any]:
    return next(p for p in d["probes"] if p["id"] == pid)


def test_water_template_is_valid_and_uses_its_own_roles(water: DomainPack) -> None:
    assert water.physics == "dependency"
    assert set(water.role_catalogue) == {"resident", "guard", "plumber", "electrician"}
    assert water.role_catalogue["plumber"].skill == "technician"
    assert "VALVE_F3.closed" in water.decision_of


def test_healthy_world_has_water_everywhere(water: DomainPack) -> None:
    table = predict(water, ())
    assert table[("tap_flows", "F3_WASHROOM")] == "flowing"
    assert table[("tank_level", "ROOF_TANK")] == "has_water"
    assert table[("pump_breaker", "ELEC_PANEL")] == "up"
    assert table[("control_display", "PUMP_ROOM")] == "lit"


def test_a_closed_valve_dries_only_its_floor(water: DomainPack) -> None:
    table = predict(water, [("VALVE_F3", "closed")])
    assert table[("tap_flows", "F3_WASHROOM")] == "dry"
    assert table[("tap_flows", "F2_WASHROOM")] == "flowing"
    assert table[("valve_f3", "SERVICE_SHAFT")] == "closed"
    assert table[("tank_level", "ROOF_TANK")] == "has_water"


def test_redundant_pumps_mask_a_single_failure(water: DomainPack) -> None:
    one = predict(water, [("PUMP_A", "dead")])
    assert one[("tap_flows", "F1_WASHROOM")] == "flowing"
    assert one[("pump_a_running", "PUMP_ROOM")] == "silent"
    assert one[("pump_b_running", "PUMP_ROOM")] == "running"
    both = predict(water, [("PUMP_A", "dead"), ("PUMP_B", "dead")])
    assert both[("tank_level", "ROOF_TANK")] == "empty"
    assert {both[("tap_flows", f"F{n}_WASHROOM")] for n in (1, 2, 3)} == {"dry"}


def test_a_tripped_breaker_propagates_through_the_chain(water: DomainPack) -> None:
    table = predict(water, [("PUMP_BREAKER", "tripped")])
    assert table[("pump_breaker", "ELEC_PANEL")] == "tripped"
    assert table[("control_display", "PUMP_ROOM")] == "blank"
    assert table[("pump_a_running", "PUMP_ROOM")] == "silent"
    assert table[("tap_flows", "F2_WASHROOM")] == "dry"
    assert table[("lights_on", "GUARD_DESK")] == "on"  # the rest of the building has power


def test_local_fault_breaks_only_the_component(water: DomainPack) -> None:
    world = World(water, frozenset({("PUMP_CONTROL", "display_dead")}))
    assert world.alive("PUMP_CONTROL")
    assert world.faulty("PUMP_CONTROL")
    table = predict(water, [("PUMP_CONTROL", "display_dead")])
    assert table[("control_display", "PUMP_ROOM")] == "blank"
    assert table[("pump_a_running", "PUMP_ROOM")] == "running"
    assert table[("tap_flows", "F3_WASHROOM")] == "flowing"


def test_upstream_outage_and_breaker_trip_are_told_apart(water: DomainPack) -> None:
    municipal = predict(water, [("MUNICIPAL", "cut")])
    breaker = predict(water, [("PUMP_BREAKER", "tripped")])
    differing = {site for site in municipal if municipal[site] != breaker[site]}
    assert ("inlet_flow", "PUMP_ROOM") in differing
    assert ("pump_breaker", "ELEC_PANEL") in differing


def test_legacy_packs_keep_their_physics() -> None:
    campus = load_pack("campus_block_c")
    assert campus.physics == "building_network"
    assert "student" in campus.role_catalogue
    table = predict(campus, [("CB_C2_7", "tripped")])
    assert table[("internet_works", "F3_R304")] == "no"


def test_unknown_requirement(raw: dict[str, Any]) -> None:
    _invalid(
        raw,
        lambda d: _component(d, "PUMP_A").update(requires=["SUMP", "NOPE"]),
        "requires 'NOPE' does not exist",
    )


def test_requirement_cycle(raw: dict[str, Any]) -> None:
    _invalid(raw, lambda d: _component(d, "GRID_FEED").update(requires=["LOBBY_LIGHTS"]), "cycle")


def test_redundant_cycle_is_also_rejected(raw: dict[str, Any]) -> None:
    _invalid(
        raw,
        lambda d: _component(d, "SUMP").update(requires=[{"any_of": ["MUNICIPAL", "VALVE_F1"]}]),
        "cycle",
    )


def test_network_fields_are_rejected(raw: dict[str, Any]) -> None:
    _invalid(
        raw,
        lambda d: _component(d, "PUMP_A").update(powered_by="GRID_FEED"),
        "uses powered_by; dependency sites use requires",
    )


def test_rule_outcome_must_be_declared(raw: dict[str, Any]) -> None:
    _invalid(raw, lambda d: _probe(d, "tap_flows").update(default="trickle"), "'trickle'")


def test_declared_outcome_must_be_reachable(raw: dict[str, Any]) -> None:
    _invalid(
        raw,
        lambda d: _probe(d, "tap_flows").update(outcomes=["flowing", "dry", "brown"]),
        "never produces 'brown'",
    )


def test_rule_probe_needs_rules(raw: dict[str, Any]) -> None:
    _invalid(raw, lambda d: _probe(d, "tap_flows").update(rules=[]), "needs rules and a default")


def test_target_reference_needs_a_binding_target(raw: dict[str, Any]) -> None:
    _invalid(
        raw,
        lambda d: _probe(d, "tap_flows").update(observes=[{"at": "F1_WASHROOM"}]),
        r"uses \$target but has no target",
    )


def test_rule_references_unknown_failure_mode(raw: dict[str, Any]) -> None:
    _invalid(
        raw,
        lambda d: _probe(d, "pump_breaker").update(
            rules=[{"when": {"fault": "$target.melted"}, "outcome": "tripped"}]
        ),
        "no failure mode 'melted'",
    )


def test_condition_must_have_exactly_one_operator(raw: dict[str, Any]) -> None:
    _invalid(
        raw,
        lambda d: _probe(d, "tank_level").update(
            rules=[{"when": {"alive": "SUMP", "faulty": "SUMP"}, "outcome": "has_water"}]
        ),
        "exactly one of",
    )


def test_roles_must_come_from_the_catalogue(raw: dict[str, Any]) -> None:
    _invalid(raw, lambda d: _probe(d, "tank_level").update(roles=["nurse"]), "unknown role 'nurse'")
    _invalid(raw, lambda d: d["actions"][0].update(roles=["student"]), "unknown role 'student'")


def test_rule_probes_need_dependency_physics(raw: dict[str, Any]) -> None:
    _invalid(raw, lambda d: d.update(physics="building_network"), "rule")


def test_nested_conditions(tmp_path: Path, raw: dict[str, Any]) -> None:
    data = copy.deepcopy(raw)
    _probe(data, "tank_level")["rules"] = [
        {
            "when": {"all": [{"not": {"alive": "PUMP_A"}}, {"not": {"alive": "PUMP_B"}}]},
            "outcome": "empty",
        },
        {"when": {"any": [{"alive": "PUMP_A"}, {"alive": "PUMP_B"}]}, "outcome": "has_water"},
    ]
    path = tmp_path / "nested.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    pack = load_pack(path)
    assert predict(pack, [("PUMP_A", "dead")])[("tank_level", "ROOF_TANK")] == "has_water"
    both = predict(pack, [("PUMP_A", "dead"), ("PUMP_B", "dead")])
    assert both[("tank_level", "ROOF_TANK")] == "empty"
