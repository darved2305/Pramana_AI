"""Sites nobody hand-modelled: described like an asset register, generated, health-checked."""

from __future__ import annotations

from typing import Any

from pramana_contracts import ParticipantSpec
from pramana_domain.builder import SiteDescription, build
from pramana_eval.health import check


def person(pid: str, role: str, skill: str, loc: str) -> ParticipantSpec:
    return ParticipantSpec.model_validate(
        {
            "id": pid,
            "display_name": pid.removeprefix("p_").title(),
            "roles": [role],
            "skill": skill,
            "location_id": loc,
            "languages": {"stt_candidates": ["hi-IN", "en-IN"]},
        }
    )


def question(en: str, hien: str, hi: str, mr: str) -> dict[str, str]:
    return {"en": en, "hi-en": hien, "hi": hi, "mr": mr}


RETAIL: dict[str, Any] = {
    "id": "retail_branch",
    "title": "Retail branch billing",
    "roles": [
        {"id": "cashier", "skill": "lay", "label": "Cashier"},
        {"id": "manager", "skill": "access", "label": "Store manager"},
        {"id": "it_vendor", "skill": "technician", "label": "IT vendor"},
        {"id": "electrician", "skill": "technician", "label": "Electrician"},
    ],
    "places": [
        {"id": "TILLS", "name": "the billing counter"},
        {
            "id": "BACK_OFFICE",
            "name": "the back office",
            "restricted": True,
            "access": ["manager", "it_vendor", "electrician"],
        },
    ],
    "equipment": [
        {"id": "MAINS", "type": "utility_supply", "name": "mains power", "at": "BACK_OFFICE"},
        {
            "id": "MCB_IT",
            "type": "breaker",
            "name": "the IT breaker",
            "at": "BACK_OFFICE",
            "needs": ["MAINS"],
        },
        {"id": "ISP", "type": "utility_supply", "name": "the internet line", "at": "BACK_OFFICE"},
        {
            "id": "ROUTER",
            "type": "network_device",
            "name": "the router",
            "at": "BACK_OFFICE",
            "needs": ["MCB_IT"],
        },
        {
            "id": "POS_1",
            "type": "terminal",
            "name": "till 1",
            "at": "TILLS",
            "needs": ["MCB_IT"],
        },
        {
            "id": "PAYMENTS",
            "type": "server",
            "name": "card payments",
            "at": "BACK_OFFICE",
            "needs": ["ROUTER", "ISP", "POS_1"],
        },
    ],
    "service_points": [
        {
            "id": "card_payment",
            "label": "A card payment goes through",
            "outcomes": ["approved", "failing"],
            "question": question(
                "At {place}, please try a one-rupee test payment. Is it approved, or failing?",
                "{place} pe ek rupaye ka test payment kijiye. Approve hua, ya fail ho raha hai?",
                "{place} पर एक रुपये का टेस्ट पेमेंट कीजिए। मंज़ूर हुआ, या फ़ेल हो रहा है?",
                "{place} वर एक रुपयाचं टेस्ट पेमेंट करा. मंजूर झालं, की फेल होतंय?",
            ),
            "served_by": {"TILLS": "PAYMENTS"},
        }
    ],
}

WARD: dict[str, Any] = {
    "id": "hospital_ward_cooling",
    "title": "Ward cooling",
    "roles": [
        {"id": "nurse", "skill": "lay", "label": "Nurse"},
        {"id": "ward_staff", "skill": "access", "label": "Ward staff"},
        {"id": "hvac_tech", "skill": "technician", "label": "HVAC technician"},
        {"id": "electrician", "skill": "technician", "label": "Electrician"},
    ],
    "places": [
        {"id": "WARD_A", "name": "ward A", "floor": 2},
        {"id": "WARD_B", "name": "ward B", "floor": 2},
        {
            "id": "PLANT",
            "name": "the roof plant room",
            "floor": 3,
            "kind": "plant_room",
            "restricted": True,
            "access": ["ward_staff", "hvac_tech", "electrician"],
        },
    ],
    "equipment": [
        {"id": "GRID", "type": "utility_supply", "name": "mains power", "at": "PLANT"},
        {
            "id": "MCB_HVAC",
            "type": "breaker",
            "name": "the HVAC breaker",
            "at": "PLANT",
            "needs": ["GRID"],
        },
        {
            "id": "CHILLER",
            "type": "chiller",
            "name": "the chiller",
            "at": "PLANT",
            "needs": ["MCB_HVAC"],
        },
        {
            "id": "AHU_A",
            "type": "air_handler",
            "name": "air handler A",
            "at": "PLANT",
            "needs": ["CHILLER"],
        },
        {
            "id": "AHU_B",
            "type": "air_handler",
            "name": "air handler B",
            "at": "PLANT",
            "needs": ["CHILLER"],
        },
    ],
    "service_points": [
        {
            "id": "room_cool",
            "label": "Cool air from the vents",
            "outcomes": ["cool", "warm"],
            "question": question(
                "In {place}, hold your hand at the air vent. Is the air cool, or warm?",
                "{place} mein vent ke paas haath rakhiye. Hawa thandi hai, ya garam?",
                "{place} में वेंट के पास हाथ रखिए। हवा ठंडी है, या गरम?",
                "{place} मध्ये व्हेंटजवळ हात धरा. हवा थंड आहे, की गरम?",
            ),
            "served_by": {"WARD_A": "AHU_A", "WARD_B": "AHU_B"},
        }
    ],
}


def test_a_retail_branch_is_diagnosable_by_its_staff() -> None:
    pack = build(SiteDescription.model_validate(RETAIL)).pack
    people = [
        person("p_cashier", "cashier", "lay", "TILLS"),
        person("p_manager", "manager", "access", "TILLS"),
        person("p_it", "it_vendor", "technician", "TILLS"),
        person("p_sparky", "electrician", "technician", "TILLS"),
    ]
    report = check(pack, people, episodes=10)
    assert report.ok, report.findings
    results = {r.hypothesis: r for r in report.faults}
    for hid in ("MCB_IT.tripped", "ISP.cut", "ROUTER.stopped"):
        assert results[hid].correct >= 7, results[hid]


def test_a_hospital_ward_is_diagnosable_and_tells_its_air_handlers_apart() -> None:
    pack = build(SiteDescription.model_validate(WARD)).pack
    people = [
        person("p_nurse_a", "nurse", "lay", "WARD_A"),
        person("p_nurse_b", "nurse", "lay", "WARD_B"),
        person("p_staff", "ward_staff", "access", "WARD_A"),
        person("p_hvac", "hvac_tech", "technician", "WARD_B"),
        person("p_sparky", "electrician", "technician", "WARD_A"),
    ]
    report = check(pack, people, episodes=10)
    assert report.ok, report.findings
    results = {r.hypothesis: r for r in report.faults}
    for hid in ("AHU_A.stopped", "CHILLER.stopped", "MCB_HVAC.tripped"):
        assert results[hid].correct >= 7, results[hid]
    assert results["AHU_A.stopped"].wrong <= 2
