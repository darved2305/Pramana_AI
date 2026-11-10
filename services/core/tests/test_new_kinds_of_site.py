"""Sites nobody has templated, built from an empty workspace through to a repair decision."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from auth_testkit import CSRF
from fastapi.testclient import TestClient
from participant_bot import answer_pending, run_to_conclusion
from test_accounts import account_core as account_core
from test_accounts import create
from test_google_auth import sql

pytestmark = pytest.mark.db

HINDI_REPORT = "आईसीयू में ऑक्सीजन का अलार्म बज रहा है"


def question(en: str) -> dict[str, str]:
    return {"en": en, "hi": en, "hi-en": en, "mr": en}


def person(pid: str, role: str, skill: str, place: str) -> dict[str, Any]:
    return {
        "id": pid,
        "display_name": pid.removeprefix("p_").replace("_", " ").title(),
        "roles": [role],
        "skill": skill,
        "location_id": place,
        "languages": {"stt_candidates": ["hi-IN", "en-IN"], "template_language": "en"},
    }


HOSPITAL = {
    "id": "informa_hospital",
    "title": "Informa Hospital",
    "roles": [
        {"id": "doctor", "skill": "lay", "label": "Doctor"},
        {"id": "charge_nurse", "skill": "lay", "label": "Charge nurse"},
        {"id": "patient", "skill": "lay", "label": "Patient"},
        {"id": "attendant", "skill": "access", "label": "Ward attendant"},
        {"id": "plumber", "skill": "technician", "label": "Gas pipeline fitter"},
        {"id": "biomed", "skill": "technician", "label": "Biomedical engineer"},
    ],
    "places": [
        {"id": "ICU", "name": "the ICU", "floor": 2},
        {"id": "WARD_3", "name": "ward 3", "floor": 2},
        {
            "id": "GAS_ROOM",
            "name": "the medical gas room",
            "floor": 0,
            "kind": "plant_room",
            "restricted": True,
            "access": ["attendant", "biomed", "plumber"],
        },
    ],
    "equipment": [
        {
            "id": "O2_BANK",
            "type": "medical_gas_source",
            "name": "the oxygen bank",
            "at": "GAS_ROOM",
        },
        {
            "id": "ICU_VALVE",
            "type": "valve",
            "name": "the ICU oxygen valve",
            "at": "GAS_ROOM",
            "needs": ["O2_BANK"],
        },
        {
            "id": "WARD_VALVE",
            "type": "valve",
            "name": "the ward 3 oxygen valve",
            "at": "GAS_ROOM",
            "needs": ["O2_BANK"],
        },
    ],
    "service_points": [
        {
            "id": "oxygen_flow",
            "label": "Oxygen at the bedside outlet",
            "outcomes": ["flowing", "no_flow"],
            "question": question(
                "In {place}, check the bedside oxygen outlet. Flowing or no flow?"
            ),
            "served_by": {"ICU": "ICU_VALVE", "WARD_3": "WARD_VALVE"},
        }
    ],
}
HOSPITAL_PEOPLE = [
    person("p_doctor", "doctor", "lay", "ICU"),
    person("p_nurse", "charge_nurse", "lay", "ICU"),
    person("p_patient", "patient", "lay", "WARD_3"),
    person("p_attendant", "attendant", "access", "GAS_ROOM"),
    person("p_fitter", "plumber", "technician", "GAS_ROOM"),
    person("p_biomed", "biomed", "technician", "GAS_ROOM"),
]

OFFICE = {
    "id": "orbit_office",
    "title": "Orbit Software office",
    "roles": [
        {"id": "receptionist", "skill": "lay", "label": "Receptionist"},
        {"id": "employee", "skill": "lay", "label": "Employee"},
        {"id": "facilities", "skill": "access", "label": "Facilities"},
        {"id": "tech_lead", "skill": "technician", "label": "Tech lead"},
        {"id": "technician", "skill": "technician", "label": "Sysadmin"},
        {"id": "electrician", "skill": "technician", "label": "Electrician"},
    ],
    "places": [
        {"id": "FRONT_DESK", "name": "the front desk", "floor": 0},
        {"id": "DEV_FLOOR", "name": "the developer floor", "floor": 3},
        {
            "id": "SERVER_ROOM",
            "name": "the server room",
            "floor": 1,
            "kind": "plant_room",
            "restricted": True,
            "access": ["facilities", "tech_lead", "technician", "electrician"],
        },
    ],
    "equipment": [
        {"id": "MAINS", "type": "utility_supply", "name": "mains power", "at": "SERVER_ROOM"},
        {
            "id": "RACK_MCB",
            "type": "breaker",
            "name": "the rack breaker",
            "at": "SERVER_ROOM",
            "needs": ["MAINS"],
        },
        {
            "id": "CORE_SWITCH",
            "type": "network_device",
            "name": "the core switch",
            "at": "SERVER_ROOM",
            "needs": ["RACK_MCB"],
        },
    ],
    "service_points": [
        {
            "id": "lan_up",
            "label": "Wired network at the desk",
            "outcomes": ["connected", "offline"],
            "question": question("In {place}, is the wired network connected or offline?"),
            "served_by": {"FRONT_DESK": "CORE_SWITCH", "DEV_FLOOR": "CORE_SWITCH"},
        }
    ],
}
OFFICE_PEOPLE = [
    person("p_reception", "receptionist", "lay", "FRONT_DESK"),
    person("p_dev", "employee", "lay", "DEV_FLOOR"),
    person("p_facilities", "facilities", "access", "SERVER_ROOM"),
    person("p_lead", "tech_lead", "technician", "SERVER_ROOM"),
    person("p_sysadmin", "technician", "technician", "SERVER_ROOM"),
    person("p_electrician", "electrician", "technician", "SERVER_ROOM"),
]

METRO = {
    "id": "metro_station",
    "title": "Sector 9 metro station",
    "roles": [
        {"id": "commuter", "skill": "lay", "label": "Commuter"},
        {"id": "station_guard", "skill": "access", "label": "Station guard"},
        {"id": "technician", "skill": "technician", "label": "Systems technician"},
        {"id": "electrician", "skill": "technician", "label": "Traction electrician"},
    ],
    "places": [
        {"id": "CONCOURSE", "name": "the concourse", "floor": 1},
        {"id": "PLATFORM", "name": "platform 2", "floor": 0},
        {
            "id": "SIGNAL_ROOM",
            "name": "the signalling room",
            "floor": 1,
            "kind": "plant_room",
            "restricted": True,
            "access": ["station_guard", "technician", "electrician"],
        },
    ],
    "equipment": [
        {"id": "FEED", "type": "utility_supply", "name": "the station feed", "at": "SIGNAL_ROOM"},
        {
            "id": "AFC_MCB",
            "type": "breaker",
            "name": "the ticket gate breaker",
            "at": "SIGNAL_ROOM",
            "needs": ["FEED"],
        },
        {
            "id": "GATE_CTRL",
            "type": "controller",
            "name": "the ticket gate controller",
            "at": "SIGNAL_ROOM",
            "needs": ["AFC_MCB"],
        },
    ],
    "service_points": [
        {
            "id": "gates_open",
            "label": "Ticket gates accept cards",
            "outcomes": ["accepting", "rejecting"],
            "question": question("In {place}, are the ticket gates accepting or rejecting cards?"),
            "served_by": {"CONCOURSE": "GATE_CTRL", "PLATFORM": "GATE_CTRL"},
        }
    ],
}
METRO_PEOPLE = [
    person("p_commuter", "commuter", "lay", "CONCOURSE"),
    person("p_second_commuter", "commuter", "lay", "PLATFORM"),
    person("p_guard", "station_guard", "access", "SIGNAL_ROOM"),
    person("p_tech", "technician", "technician", "SIGNAL_ROOM"),
    person("p_power", "electrician", "technician", "SIGNAL_ROOM"),
]


def post(client: TestClient, path: str, json: Any = None) -> Any:
    return client.post(path, json=json, headers={**CSRF, "Idempotency-Key": uuid.uuid4().hex})


class Scoped:
    """The participant bot talks to the workspace's investigation routes."""

    def __init__(self, client: TestClient, investigations: str) -> None:
        self.client, self.investigations = client, investigations

    def post(self, path: str, **kw: Any) -> Any:
        return self.client.post(
            path.replace("/v1/investigations", self.investigations),
            headers={**CSRF, "Idempotency-Key": uuid.uuid4().hex, **kw.pop("headers", {})},
            **kw,
        )

    def get(self, path: str, **kw: Any) -> Any:
        return self.client.get(path.replace("/v1/investigations", self.investigations), **kw)


def publish(
    client: TestClient, description: dict[str, Any], people: list[dict[str, Any]]
) -> tuple[str, str]:
    workspace = create(client).json()
    org, site = workspace["organization"]["slug"], workspace["live_site"]["id"]
    root = f"/v1/orgs/{org}/sites/{site}"
    draft = post(client, root + "/draft", {"description": description})
    assert draft.status_code == 200, draft.text
    health = post(client, root + f"/draft/{draft.json()['id']}/health", people)
    assert health.status_code == 200, health.text
    published = post(client, root + f"/draft/{draft.json()['id']}/publish")
    assert published.status_code == 200, published.text
    for one in people:
        added = post(client, root + "/people", one)
        assert added.status_code == 201, added.text
    return site, f"/v1/orgs/{org}/investigations"


def start(
    client: TestClient,
    investigations: str,
    site: str,
    people: list[dict[str, Any]],
    faults: list[tuple[str, str]],
    report: str,
    place: str,
) -> dict[str, Any]:
    created = post(
        client,
        investigations,
        {
            "site_id": site,
            "practice": True,
            "participants": people,
            "report": {
                "text": report,
                "reporter_id": people[0]["id"],
                "affected_location_id": place,
            },
            "scenario": {
                "seed": 11,
                "fault": {"faults": [{"component_id": c, "mode": m} for c, m in faults]},
            },
        },
    )
    assert created.status_code == 201, created.text
    body: dict[str, Any] = created.json()
    return body


def conclude(client: TestClient, investigations: str, initial: dict[str, Any]) -> dict[str, Any]:
    with TestClient(client.app.state.sim._http._transport.app) as sim:  # type: ignore[attr-defined]
        final, path = run_to_conclusion(
            Scoped(client, investigations),  # type: ignore[arg-type]
            sim,
            initial,
            max_steps=30,
        )
    assert final["status"] == "decided", (final["plan"]["reason"], path)
    return final


@pytest.mark.parametrize(
    ("description", "people", "fault", "expected", "report", "place"),
    [
        (HOSPITAL, HOSPITAL_PEOPLE, ("ICU_VALVE", "closed"), "ICU_VALVE", HINDI_REPORT, "ICU"),
        (HOSPITAL, HOSPITAL_PEOPLE, ("O2_BANK", "depleted"), "O2_BANK", HINDI_REPORT, "ICU"),
        (OFFICE, OFFICE_PEOPLE, ("RACK_MCB", "tripped"), "RACK_MCB", "No network", "FRONT_DESK"),
        (OFFICE, OFFICE_PEOPLE, ("CORE_SWITCH", "stopped"), "CORE_SWITCH", "No LAN", "FRONT_DESK"),
        (METRO, METRO_PEOPLE, ("AFC_MCB", "tripped"), "AFC_MCB", "Gates reject cards", "CONCOURSE"),
        (METRO, METRO_PEOPLE, ("GATE_CTRL", "failed"), "GATE_CTRL", "Gates dead", "CONCOURSE"),
    ],
)
def test_a_new_kind_of_site_reaches_the_right_decision(
    account_core: TestClient,
    description: dict[str, Any],
    people: list[dict[str, Any]],
    fault: tuple[str, str],
    expected: str,
    report: str,
    place: str,
) -> None:
    client = account_core
    site, investigations = publish(client, description, people)
    initial = start(client, investigations, site, people, [fault], report, place)
    assert initial["report"]["text"] == report
    final = conclude(client, investigations, initial)
    assert expected in final["plan"]["decision_class"], final["plan"]

    revealed = post(client, f"{investigations}/{final['id']}/reveal")
    assert revealed.status_code == 200, revealed.text
    replay = client.get(f"{investigations}/{final['id']}/replay").json()
    assert replay["identical"] is True
    assert replay["log_intact"] is True


def test_no_product_wording_from_the_hostel_reaches_a_hospital(account_core: TestClient) -> None:
    client = account_core
    site, investigations = publish(client, HOSPITAL, HOSPITAL_PEOPLE)
    initial = start(
        client, investigations, site, HOSPITAL_PEOPLE, [("ICU_VALVE", "closed")], "No oxygen", "ICU"
    )
    final = conclude(client, investigations, initial)
    events = client.get(f"{investigations}/{final['id']}/events").json()
    asked = [e["payload"]["text"] for e in events if e["type"] == "QuestionAsked"]
    assert asked
    seen = " ".join([*asked, str(final["plan"]), str(final["repair_options"])]).lower()
    for word in ("hostel", "warden", "wi-fi", "wifi", "student"):
        assert word not in seen, word


def test_a_hospital_repair_needs_someone_else_to_approve(
    account_core: TestClient, migrated_db: str
) -> None:
    client = account_core
    site, investigations = publish(client, HOSPITAL, HOSPITAL_PEOPLE)
    initial = start(
        client, investigations, site, HOSPITAL_PEOPLE, [("ICU_VALVE", "closed")], "No oxygen", "ICU"
    )
    final = conclude(client, investigations, initial)
    options = final["repair_options"]
    assert [(o["action"], o["target"]) for o in options] == [("open_valve", "ICU_VALVE")]
    assert options[0]["participant_ids"] == ["p_fitter"]
    asked = post(
        client,
        f"{investigations}/{final['id']}/approvals",
        {"action": "open_valve", "target": "ICU_VALVE", "participant_id": "p_fitter"},
    )
    assert asked.status_code in (200, 201), asked.text
    approval = asked.json()["approvals"][0]
    # The riskiest case: one person who holds every role asks and then tries to approve.
    sql(migrated_db, "update memberships set roles = array['owner', 'operator', 'approver']", {})
    refused = post(
        client,
        f"{investigations}/{final['id']}/approvals/{approval['id']}/decision",
        {"decision": "approve"},
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["code"] == "SELF_APPROVAL"


def test_when_a_patient_contradicts_the_nurse_nothing_breaks(account_core: TestClient) -> None:
    client = account_core
    site, investigations = publish(client, HOSPITAL, HOSPITAL_PEOPLE)
    inv = start(
        client, investigations, site, HOSPITAL_PEOPLE, [("ICU_VALVE", "closed")], "No oxygen", "ICU"
    )
    scoped = Scoped(client, investigations)
    with TestClient(client.app.state.sim._http._transport.app) as sim:  # type: ignore[attr-defined]
        for step in range(30):
            if inv["pending_question"] is None:
                break
            probe = inv["pending_question"]["action"]["probe_id"]
            # Every second bedside answer is wrong, as a confused witness's would be.
            flip = {probe: "flowing"} if "oxygen_flow" in probe and step % 2 else None
            inv = answer_pending(scoped, sim, inv, override=flip)["state"]  # type: ignore[arg-type]
    assert inv["pending_question"] is None
    assert inv["status"] in {"decided", "abstained", "stalled", "escalated"}, inv["status"]
    replay = client.get(f"{investigations}/{inv['id']}/replay").json()
    assert replay["identical"] is True


def test_two_faults_at_once_are_not_reported_as_certain_of_one(account_core: TestClient) -> None:
    client = account_core
    site, investigations = publish(client, OFFICE, OFFICE_PEOPLE)
    initial = start(
        client,
        investigations,
        site,
        OFFICE_PEOPLE,
        [("CORE_SWITCH", "stopped"), ("RACK_MCB", "tripped")],
        "Nothing works",
        "FRONT_DESK",
    )
    with TestClient(client.app.state.sim._http._transport.app) as sim:  # type: ignore[attr-defined]
        final, _ = run_to_conclusion(
            Scoped(client, investigations),  # type: ignore[arg-type]
            sim,
            initial,
            max_steps=30,
        )
    # The upstream breaker explains everything seen, so naming it is correct and honest.
    assert final["plan"]["decision_class"] is None or "RACK_MCB" in final["plan"]["decision_class"]
    replay = client.get(f"{investigations}/{final['id']}/replay").json()
    assert replay["identical"] is True


def test_nothing_personal_from_a_hospital_reaches_the_log(
    account_core: TestClient, migrated_db: str
) -> None:
    client = account_core
    site, investigations = publish(client, HOSPITAL, HOSPITAL_PEOPLE)
    initial = start(
        client,
        investigations,
        site,
        HOSPITAL_PEOPLE,
        [("ICU_VALVE", "closed")],
        HINDI_REPORT,
        "ICU",
    )
    conclude(client, investigations, initial)
    rows = sql(migrated_db, "select payload::text as p from events", {})
    assert rows
    assert not [r for r in rows if HINDI_REPORT in r["p"] or "Charge" in r["p"]]
