"""The model health check judges a site model against the people who would be asked."""

from __future__ import annotations

import copy

import pytest
import yaml

from pramana_contracts import ParticipantSpec
from pramana_domain import DomainPack, load_pack
from pramana_domain.pack import default_packs_dir
from pramana_eval.health import HealthReport, check

WATER = default_packs_dir() / "templates" / "building_water_supply.yaml"


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


STAFF = [
    person("p_reporter", "resident", "lay", "F3_WASHROOM"),
    person("p_guard", "guard", "access", "GUARD_DESK"),
    person("p_plumber", "plumber", "technician", "GUARD_DESK"),
    person("p_electrician", "electrician", "technician", "GUARD_DESK"),
]


@pytest.fixture(scope="module")
def water() -> DomainPack:
    return load_pack(WATER)


@pytest.fixture(scope="module")
def staffed(water: DomainPack) -> HealthReport:
    return check(water, STAFF, episodes=30)


def codes(report: HealthReport) -> set[str]:
    return {f.code for f in report.findings}


def test_a_staffed_water_site_is_healthy(staffed: HealthReport) -> None:
    assert staffed.ok, staffed.findings
    by_id = {r.hypothesis: r for r in staffed.faults}
    for hid in ("VALVE_F3.closed", "PUMP_BREAKER.tripped", "MUNICIPAL.cut", "GRID_FEED.lost"):
        r = by_id[hid]
        assert r.reportable
        # Measured over 40 runs and two seeds: 75-95% correct, at most 7.5% wrong.
        assert r.correct >= 0.6 * r.episodes, r
        assert r.wrong <= 0.15 * r.episodes, r


def test_faults_nobody_would_notice_are_not_simulated(staffed: HealthReport) -> None:
    by_id = {r.hypothesis: r for r in staffed.faults}
    # One pump failing is masked by the other; a floor 1 valve does not affect the reporter.
    assert not by_id["PUMP_A.dead"].reportable
    assert not by_id["VALVE_F1.closed"].reportable
    assert by_id["PUMP_A.dead"].episodes == 0


def test_without_access_the_site_cannot_be_diagnosed_and_the_engine_never_guesses(
    water: DomainPack,
) -> None:
    report = check(water, STAFF[:1], episodes=8)
    assert not report.ok
    assert {"INDISTINGUISHABLE", "UNREACHABLE_CHECK", "NO_ONE_TO_REPAIR"} <= codes(report)
    simulated = [r for r in report.faults if r.episodes]
    assert simulated
    assert all(r.wrong == 0 and r.correct == 0 for r in simulated)  # it abstains instead
    look_alike = next(f for f in report.findings if f.code == "INDISTINGUISHABLE")
    assert "would tell them apart" in look_alike.message


def test_one_decision_for_several_targets_is_flagged(water: DomainPack) -> None:
    raw = yaml.safe_load(WATER.read_text(encoding="utf-8"))
    merged = copy.deepcopy(raw)
    valves = [d for d in merged["decision_classes"] if d["id"].startswith("OPEN_VALVE_")]
    merged["decision_classes"] = [
        d for d in merged["decision_classes"] if not d["id"].startswith("OPEN_VALVE_")
    ] + [
        {
            "id": "SEND_PLUMBER",
            "label": "Send the plumber to the shaft",
            "hypotheses": [h for d in valves for h in d["hypotheses"]],
        }
    ]
    for act in merged["actions"]:
        if act["id"] == "open_valve":
            act["decision_classes"] = ["SEND_PLUMBER"]
    report = check(DomainPack.model_validate(merged), STAFF, episodes=0)
    assert "SPLIT_TARGET_DECISION" in codes(report)
    assert "SPLIT_TARGET_DECISION" not in codes(check(water, STAFF, episodes=0))


def test_a_fault_no_check_can_see_is_an_error(water: DomainPack) -> None:
    raw = yaml.safe_load(WATER.read_text(encoding="utf-8"))
    raw["components"].append(
        {
            "id": "HIDDEN_LEAK",
            "kind": "pipe",
            "label": "Hidden pipe",
            "failure_modes": [{"id": "leaking", "prior": 0.001, "label": "Hidden pipe leaking"}],
        }
    )
    raw["decision_classes"].append(
        {"id": "FIND_LEAK", "label": "Look for the leak", "hypotheses": ["HIDDEN_LEAK.leaking"]}
    )
    report = check(DomainPack.model_validate(raw), STAFF, episodes=0)
    assert not report.ok
    assert "SILENT_FAULT" in codes(report)


def test_the_check_is_reproducible(water: DomainPack) -> None:
    assert check(water, STAFF, episodes=4) == check(water, STAFF, episodes=4)


def test_the_campus_model_is_healthy_with_its_demo_cast() -> None:
    campus = load_pack("campus_block_c")
    cast = [
        person("p_riya", "student", "lay", "F3_R304"),
        person("p_mahesh", "guard", "access", "GUARD_DESK"),
        person("p_imran", "electrician", "technician", "MAINT_ROOM"),
        person("p_it", "it_tech", "technician", "MAINT_ROOM"),
    ]
    report = check(campus, cast, episodes=6)
    assert report.ok, report.findings
    cb = next(r for r in report.faults if r.hypothesis == "CB_C2_7.tripped")
    assert cb.correct >= 5
    # A real finding about the demo model: one decision covers two breakers.
    assert "SPLIT_TARGET_DECISION" in codes(report)
