"""Demo scenarios run through the same core and simulator interfaces as the console."""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import httpx
import pytest
from auth_testkit import AUTO, login, secure_core
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))

from demo_rehearse import RehearsalError, _approver_client, run_rehearsal, scenario_request  # noqa: E402
from text_investigation import create_investigation  # noqa: E402

__all__ = ["secure_core"]


class ApproverSession:
    """Use the signed-in session without the operator automation header."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def _request(self, method: str, *args: object, **kwargs: object) -> httpx.Response:
        key = self.client.headers.pop("X-Automation-Key", None)
        try:
            return getattr(self.client, method)(*args, **kwargs)
        finally:
            if key is not None:
                self.client.headers["X-Automation-Key"] = key

    def get(self, *args: object, **kwargs: object) -> httpx.Response:
        return self._request("get", *args, **kwargs)

    def post(self, *args: object, **kwargs: object) -> httpx.Response:
        return self._request("post", *args, **kwargs)


def test_s1_rehearsal_runs_parallel_approval_repair_verification_reveal_and_replay(
    secure_core: TestClient,
) -> None:
    core = secure_core
    core.headers.update(AUTO)
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    timeline = io.StringIO()
    login(core, "approver")

    result = run_rehearsal(
        core,
        sim,
        scenario="S1",
        output=timeline,
        seed=19,
        approver=ApproverSession(core),  # type: ignore[arg-type]
    )

    assert result["skipped"] is False
    assert result["parallelism"] == 3
    assert result["max_parallel_observed"] == 3
    assert result["verification_status"] == "verified"
    assert result["reveal"]["ground_truth"]["correct"] is True
    reveal = result["reveal"]["ground_truth"]["reveal"]
    assert reveal["commitment_verified"] is True
    assert result["replay"]["identical"] is True
    assert result["replay"]["recorded_sha256"] == result["replay"]["replayed_sha256"]
    assert "People asked at once: 3" in timeline.getvalue()
    assert "approved by " + core.user_ids["approver"] in timeline.getvalue()  # type: ignore[attr-defined]
    assert "verified" in timeline.getvalue()
    assert "replay identical" in timeline.getvalue()

    events = core.get(f"/v1/investigations/{result['investigation_id']}/events").json()
    decisions = [event["payload"] for event in events if event["type"] == "ApprovalDecided"]
    assert len(decisions) == 1
    assert decisions[0]["approver_id"] == core.user_ids["approver"]  # type: ignore[attr-defined]
    assert decisions[0]["approver_id"] != "automation"


def test_s1_without_an_authenticated_approver_is_rejected_before_creation(core: TestClient) -> None:
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    before = core.get("/v1/investigations").json()["total"]

    with pytest.raises(RehearsalError, match="authenticated approver"):
        run_rehearsal(core, sim, scenario="S1", output=io.StringIO())

    assert core.get("/v1/investigations").json()["total"] == before


def test_approver_client_requires_both_credentials() -> None:
    with pytest.raises(RehearsalError, match="PRAMANA_APPROVER_EMAIL"):
        _approver_client("https://core.test", {})


def test_approver_client_rejects_accounts_with_operator_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_client = httpx.Client

    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"method": "session", "roles": ["operator", "approver"]})

    def client_factory(*, base_url: str, timeout: float, follow_redirects: bool) -> httpx.Client:
        return original_client(
            transport=httpx.MockTransport(respond),
            base_url=base_url,
            timeout=timeout,
            follow_redirects=follow_redirects,
        )

    monkeypatch.setattr(httpx, "Client", client_factory)
    with pytest.raises(RehearsalError, match="approver-only"):
        _approver_client(
            "https://core.test",
            {"PRAMANA_APPROVER_EMAIL": "approver@example.test", "PRAMANA_APPROVER_PASSWORD": "pw"},
        )


def test_scenario_request_matches_the_console_fields_and_keeps_empty_participants() -> None:
    s1 = scenario_request("S1", seed=19)
    assert s1["max_parallel_calls"] == 3
    assert s1["presence_checks"] is False
    assert len(s1["participants"]) == 3
    assert s1["scenario"]["fault"] == {"faults": [{"component_id": "CB_C2_7", "mode": "tripped"}]}

    s2 = scenario_request("S2", seed=19)
    assert s2["report"]["reporter_id"] == "p_neha"
    assert {p["location_id"] for p in s2["participants"]} == {"F2_R210", "F2_R205"}
    assert s2["scenario"]["fault"] == {"faults": [{"component_id": "AP_2A", "mode": "dead"}]}

    s7 = scenario_request("S7", seed=19)
    assert s7["presence_checks"] is True
    assert [person["id"] for person in s7["participants"]] == ["p_riya", "p_mahesh"]
    assert s7["scenario"]["fault"] == {"faults": [{"component_id": "SW_C2", "mode": "dead"}]}

    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(201, json={})

    with httpx.Client(transport=httpx.MockTransport(respond), base_url="https://core.test") as core:
        create_investigation(core, seed=19, participants=[])
    assert requests[0]["participants"] == []


def test_s2_rehearsal_uses_main_scenario_and_reveals_disagreement(core: TestClient) -> None:
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    timeline = io.StringIO()

    result = run_rehearsal(core, sim, scenario="S2", output=timeline, seed=19)

    state = core.get(f"/v1/investigations/{result['investigation_id']}").json()
    assert result["skipped"] is False
    assert [p["id"] for p in state["participants"]] == ["p_neha", "p_aarav"]
    assert state["report"]["reporter_id"] == "p_neha"
    assert state["presence_checks_enabled"] is False
    assert state["disagreements"]
    assert state["disagreements"][-1]["reconciling_hypothesis"] == "AP_2A.dead"
    assert result["reveal"]["ground_truth"]["correct"] is True
    assert result["replay"]["identical"] is True
    assert "replay identical" in timeline.getvalue()


def test_s7_adversary_fails_label_check_from_guard_desk(core: TestClient) -> None:
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    timeline = io.StringIO()

    result = run_rehearsal(core, sim, scenario="S7", output=timeline, seed=19, variant="adversary")

    state = core.get(f"/v1/investigations/{result['investigation_id']}").json()
    assert state["presence_checks_enabled"] is True
    assert [check["status"] for check in state["presence_checks"]] == ["failed"]
    assert result["replay"]["identical"] is True
    assert "IDF-2" in timeline.getvalue()
    assert "failed" in timeline.getvalue().lower()


def test_s7_honest_participant_reads_the_label_and_passes(core: TestClient) -> None:
    sim = TestClient(core.sim_app)  # type: ignore[attr-defined]
    timeline = io.StringIO()

    result = run_rehearsal(core, sim, scenario="S7", output=timeline, seed=19, variant="honest")

    state = core.get(f"/v1/investigations/{result['investigation_id']}").json()
    assert state["presence_checks_enabled"] is True
    assert [check["status"] for check in state["presence_checks"]] == ["passed"]
    assert result["replay"]["identical"] is True
    assert "label" in timeline.getvalue().lower()
