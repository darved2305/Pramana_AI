"""Any site, described like an asset register, becomes a valid investigation model."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from pramana_domain import World, predict
from pramana_domain.builder import SiteDescription, build
from pramana_domain.library import LIBRARY
from pramana_domain.spec_storage import load_spec, spec_digest

TAP = {
    "id": "tap_flows",
    "label": "Water comes from the tap",
    "outcomes": ["flowing", "dry"],
    "question": {
        "en": "In {place}, please open a tap. Is water coming out, or is it dry?",
        "hi-en": "{place} mein ek tap kholiye. Paani aa raha hai, ya sukha hai?",
        "hi": "{place} में एक नल खोलिए। पानी आ रहा है, या सूखा है?",
        "mr": "{place} मध्ये एक नळ उघडा. पाणी येतंय, की कोरडा आहे?",
    },
    "served_by": {"F1_WASHROOM": "VALVE_F1", "F2_WASHROOM": "VALVE_F2"},
}


def water_site() -> dict[str, Any]:
    return {
        "id": "office_water",
        "title": "Office water supply",
        "roles": [
            {"id": "staff", "skill": "lay", "label": "Office staff"},
            {"id": "guard", "skill": "access", "label": "Security guard"},
            {"id": "plumber", "skill": "technician", "label": "Plumber"},
            {"id": "electrician", "skill": "technician", "label": "Electrician"},
        ],
        "places": [
            {"id": "LOBBY", "name": "the lobby", "floor": 0},
            {
                "id": "PUMP_ROOM",
                "name": {"en": "the pump room", "hi": "पंप रूम", "mr": "पंप रूम"},
                "floor": 0,
                "kind": "plant_room",
                "restricted": True,
                "access": ["guard", "plumber", "electrician"],
            },
            {"id": "F1_WASHROOM", "name": "the first-floor washroom", "floor": 1},
            {"id": "F2_WASHROOM", "name": "the second-floor washroom", "floor": 2},
        ],
        "equipment": [
            {"id": "GRID", "type": "utility_supply", "name": "mains power", "at": "PUMP_ROOM"},
            {
                "id": "PUMP_MCB",
                "type": "breaker",
                "name": "the pump breaker",
                "at": "PUMP_ROOM",
                "needs": ["GRID"],
            },
            {"id": "CITY", "type": "utility_supply", "name": "city water", "at": "PUMP_ROOM"},
            {
                "id": "PUMP_A",
                "type": "pump",
                "name": "pump A",
                "at": "PUMP_ROOM",
                "needs": ["PUMP_MCB", "CITY"],
            },
            {
                "id": "PUMP_B",
                "type": "pump",
                "name": "pump B",
                "at": "PUMP_ROOM",
                "needs": ["PUMP_MCB", "CITY"],
            },
            {
                "id": "VALVE_F1",
                "type": "valve",
                "name": "the floor 1 valve",
                "at": "PUMP_ROOM",
                "needs": [{"any_of": ["PUMP_A", "PUMP_B"]}],
            },
            {
                "id": "VALVE_F2",
                "type": "valve",
                "name": "the floor 2 valve",
                "at": "PUMP_ROOM",
                "needs": [{"any_of": ["PUMP_A", "PUMP_B"]}],
            },
        ],
        "service_points": [copy.deepcopy(TAP)],
    }


def test_a_described_site_builds_a_valid_dependency_model() -> None:
    result = build(SiteDescription.model_validate(water_site()))
    pack = result.pack
    assert pack.physics == "dependency"
    assert set(pack.role_catalogue) == {"staff", "guard", "plumber", "electrician"}
    # One decision per fault, so the engine must find the exact target before a repair.
    assert all(len(d.hypotheses) == 1 for d in pack.decision_classes)
    assert {a.id for a in pack.actions} == {"reset_breaker", "open_valve"}
    assert next(a for a in pack.actions if a.id == "open_valve").roles == ["plumber"]


def test_generated_physics_follows_the_dependencies() -> None:
    pack = build(SiteDescription.model_validate(water_site())).pack
    assert predict(pack, ())[("tap_flows", "F2_WASHROOM")] == "flowing"
    tripped = predict(pack, [("PUMP_MCB", "tripped")])
    assert tripped[("tap_flows", "F1_WASHROOM")] == "dry"
    assert tripped[("pump_mcb_position", "PUMP_ROOM")] == "tripped"
    one_pump = predict(pack, [("PUMP_A", "failed")])
    assert one_pump[("tap_flows", "F1_WASHROOM")] == "flowing"  # pump B covers it
    assert one_pump[("pump_a_running", "PUMP_ROOM")] == "stopped"
    closed = World(pack, frozenset({("VALVE_F2", "closed")}))
    assert closed.observe(pack.probe_by_id["tap_flows"], "F1_WASHROOM") == "flowing"
    assert closed.observe(pack.probe_by_id["tap_flows"], "F2_WASHROOM") == "dry"


def test_checks_respect_skills_and_access() -> None:
    pack = build(SiteDescription.model_validate(water_site())).pack
    breaker = pack.probe_by_id["pump_mcb_position"]
    assert set(breaker.roles) == {"plumber", "electrician"}  # technicians allowed in
    running = pack.probe_by_id["pump_a_running"]
    assert "staff" not in running.roles  # office staff may not enter the pump room
    assert "guard" in running.roles


def test_names_are_filled_into_every_language() -> None:
    pack = build(SiteDescription.model_validate(water_site())).pack
    probe = pack.probe_by_id["pump_a_running"]
    assert "pump A" in probe.templates["en"]
    assert "{name}" not in "".join(probe.templates.values())
    room = pack.location_by_id["PUMP_ROOM"]
    assert room.label.hi == "पंप रूम"
    assert room.label.get("hi-en") == "the pump room"


def test_walks_are_generated_from_floors() -> None:
    pack = build(SiteDescription.model_validate(water_site())).pack
    assert pack.walk_seconds("LOBBY", "F2_WASHROOM") is not None
    assert pack.walk_seconds("PUMP_ROOM", "F1_WASHROOM") is not None


def test_the_generated_model_is_stored_byte_stable() -> None:
    a = build(SiteDescription.model_validate(water_site())).spec
    b = build(SiteDescription.model_validate(water_site())).spec
    assert spec_digest(a) == spec_digest(b)
    assert load_spec(a) == load_spec(b)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda d: d["equipment"][3].update(needs=["NOPE"]), "needs 'NOPE'"),
        (lambda d: d["equipment"][0].update(type="teleporter"), "unknown equipment type"),
        (lambda d: d["places"][1].update(access=[]), "say which roles may enter"),
        (lambda d: d["service_points"][0]["served_by"].update(ROOF="VALVE_F1"), "'ROOF'"),
        (lambda d: d["equipment"][3].update(priors={"melted": 0.1}), "cannot fail as 'melted'"),
    ],
)
def test_description_errors_are_readable(mutate: Any, match: str) -> None:
    data = water_site()
    mutate(data)
    with pytest.raises(ValidationError, match=match):
        SiteDescription.model_validate(data)


def test_a_dependency_loop_is_reported() -> None:
    data = water_site()
    data["equipment"][0]["needs"] = ["PUMP_A"]
    with pytest.raises(ValidationError, match="cycle"):
        build(SiteDescription.model_validate(data))


def test_every_library_type_builds() -> None:
    """Each equipment type yields a valid model on its own, behind a breaker."""
    for type_id in LIBRARY:
        desc = {
            "id": "one_thing",
            "title": "One thing",
            "roles": [
                {"id": "user", "skill": "lay", "label": "User"},
                {"id": "tech", "skill": "technician", "label": "Technician"},
            ],
            "places": [{"id": "HALL", "name": "the hall"}],
            "equipment": [
                {"id": "MCB", "type": "breaker", "name": "the breaker", "at": "HALL"},
                {
                    "id": "THING",
                    "type": type_id,
                    "name": "the unit",
                    "at": "HALL",
                    "needs": ["MCB"],
                },
            ],
            "service_points": [
                {
                    **TAP,
                    "id": "works",
                    "outcomes": ["works", "broken"],
                    "served_by": {"HALL": "THING"},
                }
            ],
        }
        pack = build(SiteDescription.model_validate(desc)).pack
        assert pack.component_by_id["THING"].kind == type_id
