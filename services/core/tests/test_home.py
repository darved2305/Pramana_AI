"""The workspace home's ordering rules (pure) and its endpoint."""

from __future__ import annotations

import pytest
from auth_testkit import CSRF
from fastapi.testclient import TestClient
from test_accounts import account_core as account_core
from test_accounts import create

from pramana_contracts import HomeInvestigation, HomeSite
from pramana_core.home import HomeFacts, plan_home

SANDBOX = HomeSite(
    id="site_a",
    name="Practice",
    mode="sandbox",
    model_version=1,
    draft="none",
    open_investigations=0,
)
OWN = HomeSite(
    id="site_b",
    name="Block B",
    mode="live",
    model_version=None,
    draft="none",
    open_investigations=0,
)


def inv(status: str, label: str | None = None) -> HomeInvestigation:
    return HomeInvestigation(
        id=f"inv_{status}",
        site_id="site_b",
        status=status,
        report_text="No water on floor 3",
        decision_label=label,
        updated_at="2026-11-08T00:00:00+00:00",
    )


def facts(**overrides: object) -> HomeFacts:
    base: dict[str, object] = {
        "display_name": "Asha Rao",
        "roles": frozenset({"owner", "operator"}),
        "sites": [SANDBOX, OWN],
    }
    base.update(overrides)
    return HomeFacts(**base)  # type: ignore[arg-type]


def ids(home: object) -> list[str]:
    return [m.id for m in home.modules]  # type: ignore[attr-defined]


def test_a_new_workspace_leads_with_setup() -> None:
    home = plan_home(facts())
    assert ids(home) == ["setup", "sites"]
    setup = home.modules[0]
    assert setup.reason == "1 of 5 steps done. Next: run a practice investigation."
    assert [s.done for s in setup.steps] == [True, False, False, False, False]
    assert home.greeting_name == "Asha"


def test_approvals_come_first_only_for_approvers() -> None:
    waiting = [inv("awaiting_approval")] * 2
    approver = plan_home(facts(roles=frozenset({"approver"}), awaiting_approval=waiting))
    assert ids(approver)[0] == "approvals"
    assert approver.modules[0].reason.startswith("2 repairs wait for your approval")
    operator = plan_home(facts(awaiting_approval=waiting))
    assert "approvals" not in ids(operator)


def test_open_work_outranks_setup_and_decisions_ask_operators_to_act() -> None:
    home = plan_home(facts(active=[inv("investigating")], decided=[inv("decided", "Open valve")]))
    assert ids(home)[:3] == ["active", "decided", "setup"]
    viewer = plan_home(
        facts(roles=frozenset({"viewer"}), active=[inv("investigating")], decided=[inv("decided")])
    )
    assert "decided" not in ids(viewer)


def test_setup_disappears_when_done_or_dismissed() -> None:
    published = OWN.model_copy(update={"model_version": 2})
    done = facts(sites=[SANDBOX, published], practice_done=True, people=3, own_investigations=1)
    assert "setup" not in ids(plan_home(done))
    assert "setup" not in ids(plan_home(facts(checklist_dismissed=True)))


def test_pins_lead_and_hides_are_left_out() -> None:
    home = plan_home(facts(recent=[inv("verified", "Opened the floor 3 valve")], pins=("recent",)))
    assert ids(home)[0] == "recent"
    assert home.modules[0].pinned
    assert home.modules[0].reason == "Most recent: Opened the floor 3 valve."
    hidden = plan_home(facts(hides=("sites",)))
    assert "sites" not in ids(hidden)
    assert hidden.hidden == ["sites"]


def test_a_draft_with_problems_is_called_out() -> None:
    draft = OWN.model_copy(update={"draft": "problems"})
    home = plan_home(facts(sites=[SANDBOX, draft]))
    sites = next(m for m in home.modules if m.id == "sites")
    assert sites.reason == "Block B has a draft model with problems to fix."


@pytest.mark.db
def test_home_endpoint_for_a_new_workspace(account_core: TestClient) -> None:
    client = account_core
    workspace = create(client).json()
    response = client.get(f"/v1/orgs/{workspace['organization']['slug']}/home")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [m["id"] for m in body["modules"]] == ["setup", "sites"]
    modes = {s["mode"] for s in body["modules"][1]["sites"]}
    assert modes == {"sandbox", "live"}
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.db
def test_preferences_are_saved_for_the_next_visit(account_core: TestClient) -> None:
    client = account_core
    workspace = create(client).json()
    org = workspace["organization"]
    headers = {**CSRF, "Idempotency-Key": "save-preferences-0001"}
    saved = client.patch(
        "/v1/me/preferences",
        json={
            "last_site": {"org_id": org["id"], "site_id": workspace["live_site"]["id"]},
            "home_layout": {"pins": ["sites"], "hides": ["setup"]},
        },
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    me = client.get("/v1/me").json()["preferences"]
    assert me["last_site_by_org"][org["id"]] == workspace["live_site"]["id"]
    assert me["home_layout"]["pins"] == ["sites"]
    home = client.get(f"/v1/orgs/{org['slug']}/home").json()
    assert [m["id"] for m in home["modules"]] == ["sites"]
    assert home["modules"][0]["pinned"] is True
    assert home["hidden"] == ["setup"]


@pytest.mark.db
def test_preferences_cannot_point_at_someone_elses_workspace(account_core: TestClient) -> None:
    client = account_core
    create(client)
    response = client.patch(
        "/v1/me/preferences",
        json={"last_org_id": "org_01JC4ZK3V0QY8H6T2W9N5M7R1S"},
        headers={**CSRF, "Idempotency-Key": "save-preferences-0002"},
    )
    assert response.status_code == 404


@pytest.mark.db
def test_another_workspace_home_is_not_found(account_core: TestClient) -> None:
    client = account_core
    create(client)
    assert client.get("/v1/orgs/not-mine-at-all/home").status_code == 404


@pytest.mark.db
def test_members_show_emails_only_to_owners_and_admins(account_core: TestClient) -> None:
    client = account_core
    workspace = create(client).json()
    members = client.get(f"/v1/orgs/{workspace['organization']['slug']}/members")
    assert members.status_code == 200, members.text
    [me] = members.json()["items"]
    assert me["you"] is True
    assert "owner" in me["roles"]
    assert me["email"]  # an owner sees addresses
    assert client.get("/v1/orgs/not-mine-at-all/members").status_code == 404


@pytest.mark.db
def test_a_published_version_carries_the_check_it_passed(account_core: TestClient) -> None:
    client = account_core
    workspace = create(client).json()
    org, site = workspace["organization"]["slug"], workspace["live_site"]["id"]
    headers = {**CSRF}
    draft = client.post(
        f"/v1/orgs/{org}/sites/{site}/draft",
        json={"template_id": "office_water"},
        headers={**headers, "Idempotency-Key": "health-carry-0001"},
    ).json()
    for step, key in (("health", "health-carry-0002"), ("publish", "health-carry-0003")):
        r = client.post(
            f"/v1/orgs/{org}/sites/{site}/draft/{draft['id']}/{step}",
            headers={**headers, "Idempotency-Key": key},
        )
        assert r.status_code == 200, r.text
    document = client.get(f"/v1/orgs/{org}/sites/{site}/models/{draft['id']}").json()
    assert document["health"]["ok"] is True
    assert document["health"]["spec_sha256"] == document["spec_sha256"]
