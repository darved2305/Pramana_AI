"""Sign-in, sessions, roles, participant tokens and the approval identity."""

from __future__ import annotations

from typing import Any

import pytest
from auth_testkit import AUTO, CSRF, PASSWORD, login, secure_core
from core_testkit import body
from fastapi.testclient import TestClient
from participant_bot import PHRASES

from pramana_core.auth.passwords import hash_password, verify_password
from pramana_core.auth.service import LoginThrottle

pytestmark = pytest.mark.db
__all__ = ["secure_core"]


def test_password_hashes_are_salted_and_verify() -> None:
    a, b = hash_password("a long password"), hash_password("a long password")
    assert a != b
    assert a.startswith("scrypt$")
    assert verify_password("a long password", a)
    assert not verify_password("a long passworD", a)
    assert not verify_password("x", "not-a-hash")
    assert not verify_password("x", "bcrypt$1$2$3$aa$bb")
    with pytest.raises(ValueError):
        hash_password("short")


def test_login_throttle_window() -> None:
    t = LoginThrottle(2, 10.0)
    t.fail("k", now=1.0)
    t.fail("k", now=2.0)
    with pytest.raises(Exception, match="too many"):
        t.check("k", now=3.0)
    t.check("k", now=12.5)  # both failures have aged out


def test_sign_in_session_and_sign_out(secure_core: TestClient) -> None:
    c = secure_core
    assert c.get("/v1/auth/session").json()["error"]["code"] == "AUTH_REQUIRED"
    r = c.post(
        "/v1/auth/login", json={"email": "  OP@Pramana.test ", "password": PASSWORD}, headers=CSRF
    )
    assert r.status_code == 200, r.text
    assert r.json()["roles"] == ["operator"]
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "pramana_session=" in cookie
    me = c.get("/v1/auth/session").json()
    assert me["email"] == "op@pramana.test"
    assert me["method"] == "session"
    assert c.post("/v1/auth/logout").json()["error"]["code"] == "CSRF_HEADER_MISSING"
    assert c.post("/v1/auth/logout", headers=CSRF).status_code == 204
    c.cookies.clear()
    assert c.get("/v1/auth/session").status_code == 401


def test_logged_out_cookie_is_dead_even_if_replayed(secure_core: TestClient) -> None:
    c = login(secure_core, "operator")
    stolen = c.cookies.get("pramana_session")
    assert c.post("/v1/auth/logout", headers=CSRF).status_code == 204
    c.cookies.set("pramana_session", stolen)
    assert c.get("/v1/auth/session").status_code == 401


def test_wrong_password_unknown_user_and_lockout(secure_core: TestClient) -> None:
    c = secure_core
    bad = {"email": "op@pramana.test", "password": "wrong password"}
    ghost = {"email": "ghost@pramana.test", "password": PASSWORD}
    r1 = c.post("/v1/auth/login", json=bad, headers=CSRF)
    r2 = c.post("/v1/auth/login", json=ghost, headers=CSRF)
    # Same answer either way: no account enumeration.
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["error"]["message"] == r2.json()["error"]["message"]
    c.post("/v1/auth/login", json=bad, headers=CSRF)
    c.post("/v1/auth/login", json=bad, headers=CSRF)
    locked = c.post(
        "/v1/auth/login", json={"email": "op@pramana.test", "password": PASSWORD}, headers=CSRF
    )
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "AUTH_RATE_LIMITED"


def test_login_needs_the_csrf_header(secure_core: TestClient) -> None:
    r = secure_core.post("/v1/auth/login", json={"email": "op@pramana.test", "password": PASSWORD})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "CSRF_HEADER_MISSING"


def test_cookie_requests_that_change_state_need_the_csrf_header(secure_core: TestClient) -> None:
    c = login(secure_core, "operator")
    r = c.post("/v1/investigations", json=body(fault="CB_C2_7.tripped"))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "CSRF_HEADER_MISSING"
    assert c.post("/v1/investigations", json=body(), headers=CSRF).status_code == 201
    assert c.get("/v1/investigations").status_code == 200  # reads need no header


def test_anonymous_and_wrong_role_are_refused(secure_core: TestClient) -> None:
    c = secure_core
    for method, path in [
        ("get", "/v1/investigations"),
        ("post", "/v1/investigations"),
        ("get", "/v1/participants"),
        ("get", "/v1/evaluation/reports"),
        ("get", "/v1/investigations/inv_x"),
    ]:
        r = c.request(method, path, json=body() if method == "post" else None)
        assert r.status_code == 401, (path, r.text)
        assert r.json()["error"]["code"] == "AUTH_REQUIRED"
    assert c.get("/v1/packs").status_code == 200  # documented layout is public
    login(c, "approver")
    r = c.post("/v1/investigations", json=body(), headers=CSRF)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ROLE_FORBIDDEN"
    assert c.get("/v1/investigations").status_code == 200


def test_bad_automation_key_is_rejected_not_ignored(secure_core: TestClient) -> None:
    r = secure_core.get("/v1/investigations", headers={"X-Automation-Key": "guess"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "AUTH_INVALID_KEY"
    assert secure_core.get("/v1/investigations", headers=AUTO).status_code == 200


def _create(c: TestClient) -> dict[str, Any]:
    r = c.post("/v1/investigations", json=body(fault="CB_C2_7.tripped"), headers=AUTO)
    assert r.status_code == 201, r.text
    return dict(r.json())


def _token(c: TestClient, inv_id: str, pid: str) -> dict[str, str]:
    r = c.post(f"/v1/investigations/{inv_id}/participants/{pid}/token", headers=AUTO)
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_participant_token_unlocks_only_their_own_actions(secure_core: TestClient) -> None:
    c = secure_core
    inv = _create(c)
    q = inv["pending_question"]
    pid = q["action"]["participant_id"]
    other = next(p["id"] for p in inv["participants"] if p["id"] != pid)
    mine = {"Authorization": f"Bearer {_token(c, inv['id'], pid)['token']}"}
    theirs = {"Authorization": f"Bearer {_token(c, inv['id'], other)['token']}"}
    answer = {"question_id": q["id"], "participant_id": pid, "text": "haan"}

    assert c.get(f"/v1/investigations/{inv['id']}", headers=mine).status_code == 200
    assert c.post(f"/v1/investigations/{inv['id']}/answers", json=answer).status_code == 401
    r = c.post(f"/v1/investigations/{inv['id']}/answers", json=answer, headers=theirs)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "PARTICIPANT_FORBIDDEN"
    # A participant cannot mint tokens, create investigations or reveal.
    assert c.post(f"/v1/investigations/{inv['id']}/reveal", headers=mine).status_code == 403
    assert (
        c.post(f"/v1/investigations/{inv['id']}/participants/{other}/token", headers=mine)
    ).status_code == 403
    forged = {"Authorization": "Bearer abc.def"}
    r = c.get(f"/v1/investigations/{inv['id']}", headers=forged)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "AUTH_INVALID_TOKEN"
    # Their own token works.
    r = c.post(f"/v1/investigations/{inv['id']}/answers", json=answer, headers=mine)
    assert r.status_code == 200, r.text


def test_token_from_another_investigation_is_refused(secure_core: TestClient) -> None:
    c = secure_core
    a, b = _create(c), _create(c)
    pid = a["pending_question"]["action"]["participant_id"]
    tok_b = {"Authorization": f"Bearer {_token(c, b['id'], pid)['token']}"}
    q = a["pending_question"]
    r = c.post(
        f"/v1/investigations/{a['id']}/answers",
        json={"question_id": q["id"], "participant_id": pid, "text": "haan"},
        headers=tok_b,
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "PARTICIPANT_FORBIDDEN"
    assert c.get(f"/v1/investigations/{a['id']}/events", headers=tok_b).status_code == 403


def _answer_truthfully(c: TestClient, sim: TestClient, inv: dict[str, Any]) -> dict[str, Any]:
    q = inv["pending_question"]
    a = q["action"]
    tok = _token(c, inv["id"], a["participant_id"])
    h = {"Authorization": f"Bearer {tok['token']}"}
    sid = tok["scenario_id"]
    if a["requires_move"]:
        assert sim.post(f"/sim/v1/scenarios/{sid}/move", json={"to": a["location_id"]}, headers=h)
    seen = sim.post(f"/sim/v1/scenarios/{sid}/observe", json={"probe_id": a["probe_id"]}, headers=h)
    r = c.post(
        f"/v1/investigations/{inv['id']}/answers",
        json={
            "question_id": q["id"],
            "participant_id": a["participant_id"],
            "text": PHRASES[seen.json()["value"]],
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    return dict(r.json()["state"])


def test_approval_records_the_signed_in_approver_not_the_body(secure_core: TestClient) -> None:
    c = secure_core
    sim = TestClient(c.sim_app)  # type: ignore[attr-defined]
    inv = _create(c)
    for _ in range(10):
        if inv["pending_question"] is None:
            break
        inv = _answer_truthfully(c, sim, inv)
    assert inv["status"] == "decided"
    url = f"/v1/investigations/{inv['id']}/approvals"
    req = {"action": "reset_breaker", "target": "CB_C2_7", "participant_id": "p_imran"}
    login(c, "approver")
    r = c.post(url, json=req, headers=CSRF)
    assert r.status_code == 403  # approvers do not request their own approvals
    aid = c.post(url, json=req, headers=AUTO).json()["approvals"][0]["id"]
    login(c, "operator")
    r = c.post(f"{url}/{aid}/decision", json={"decision": "approve"}, headers=CSRF)
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "ROLE_FORBIDDEN"
    login(c, "approver")
    r = c.post(
        f"{url}/{aid}/decision",
        json={"decision": "approve", "approver_id": "someone_else"},
        headers=CSRF,
    )
    assert r.status_code == 200, r.text
    approval = r.json()["approvals"][0]
    assert approval["approver_id"] == c.user_ids["approver"]  # type: ignore[attr-defined]
    events = c.get(f"/v1/investigations/{inv['id']}/events").json()
    decided = next(e for e in events if e["type"] == "ApprovalDecided")
    assert decided["payload"]["approver_id"] == c.user_ids["approver"]  # type: ignore[attr-defined]
    # Only the named executor, with their own link, collects the capability.
    imran = {"Authorization": f"Bearer {_token(c, inv['id'], 'p_imran')['token']}"}
    riya = {"Authorization": f"Bearer {_token(c, inv['id'], 'p_riya')['token']}"}
    cap = f"{url}/{aid}/capability"
    assert c.post(cap, params={"participant_id": "p_imran"}, headers=riya).status_code == 403
    grant = c.post(cap, params={"participant_id": "p_imran"}, headers=imran)
    assert grant.status_code == 200
    assert grant.json()["location_id"] == "DB_C2_PANEL"  # the executor must stand here to act


def test_open_mode_keeps_body_approver_for_tests(core: TestClient) -> None:
    """With sign-in not enforced (``PRAMANA_MODE=test``), the session route says so."""
    me = core.get("/v1/auth/session").json()
    assert me["method"] == "open"
    assert set(me["roles"]) == {"operator", "approver"}
