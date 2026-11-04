# No ``from __future__ import annotations``: FastAPI resolves dependency annotations at runtime.
"""Request authentication and role checks (docs/adr/0010-authentication.md).

Three kinds of caller:

* **Staff** sign in and hold an httpOnly session cookie. Unsafe methods sent with that cookie
  must carry ``X-Pramana-CSRF: 1``: a cross-site page cannot add a custom header without a CORS
  preflight, which the core refuses for other origins (OWASP "custom request headers").
* **Participants** hold the Ed25519 token from their join link (``Authorization: Bearer``). It
  is scoped to one scenario and one person, and only unlocks that person's own actions.
* **Automation** (scripts, bots, the benchmark) sends ``X-Automation-Key``: operator + approver.
"""

import hmac
from collections.abc import Awaitable, Callable
from typing import Annotated

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import Depends, Request
from sqlalchemy import select
from starlette.requests import HTTPConnection

from pramana_contracts import StaffRole
from pramana_contracts.tokens import TokenError, private_key_from_b64, verify

from ..db import InvestigationRow
from ..errors import ApiError, not_found
from ..settings import Settings
from .service import AuthService, Principal

SESSION_COOKIE = "pramana_session"
CSRF_HEADER = "x-pramana-csrf"
AUTOMATION_HEADER = "x-automation-key"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
ALL_STAFF = frozenset(r.value for r in StaffRole)

OPEN = Principal(kind="open", id="open", display_name="Sign-in not enforced", roles=ALL_STAFF)
ANONYMOUS = Principal(kind="anonymous", id="anonymous")


def _settings(request: HTTPConnection) -> Settings:
    cfg: Settings = request.app.state.settings
    return cfg


async def current_principal(request: HTTPConnection) -> Principal:
    """Identify the caller. Never raises for a missing identity: role checks do that."""
    cached: Principal | None = getattr(request.state, "principal", None)
    if cached is not None:
        return cached
    principal = await _identify(request)
    request.state.principal = principal
    return principal


async def _identify(request: HTTPConnection) -> Principal:
    cfg = _settings(request)
    if not cfg.enforce_auth:
        return OPEN
    presented = request.headers.get(AUTOMATION_HEADER)
    if presented is not None:
        key = cfg.automation_key.get_secret_value() if cfg.automation_key else ""
        if key and hmac.compare_digest(presented.encode(), key.encode()):
            return Principal(
                kind="automation", id="automation", display_name="Automation", roles=ALL_STAFF
            )
        raise ApiError(401, "AUTH_INVALID_KEY", "the automation key is not valid")
    bearer = request.headers.get("authorization", "")
    if bearer.lower().startswith("bearer "):
        try:
            claims = verify(request.app.state.participant_public_key, bearer[7:].strip())
        except TokenError as exc:
            raise ApiError(401, "AUTH_INVALID_TOKEN", f"participant token rejected: {exc}") from exc
        return Principal(
            kind="participant",
            id=claims.sub,
            display_name=claims.sub,
            participant_id=claims.sub,
            scenario_id=claims.scn,
        )
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        auth: AuthService = request.app.state.auth
        principal = await auth.resolve(token)
        if principal is None:
            return ANONYMOUS
        # A WebSocket handshake is a GET; SameSite=Lax keeps the cookie off cross-site ones.
        method = request.scope.get("method", "GET")
        if method not in SAFE_METHODS and request.headers.get(CSRF_HEADER) != "1":
            raise ApiError(403, "CSRF_HEADER_MISSING", "send X-Pramana-CSRF: 1 with this request")
        return principal
    return ANONYMOUS


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def require_staff(*roles: StaffRole) -> Callable[[Request], Awaitable[Principal]]:
    """Any signed-in staff member, or, when ``roles`` are given, one holding any of them."""

    async def dependency(request: Request) -> Principal:
        p = await current_principal(request)
        if p.kind in ("anonymous", "participant"):
            if p.kind == "participant":
                raise ApiError(403, "ROLE_FORBIDDEN", "participants cannot do this")
            raise ApiError(401, "AUTH_REQUIRED", "sign in first")
        if roles and not any(p.has(r) for r in roles):
            needed = " or ".join(r.value for r in roles)
            raise ApiError(403, "ROLE_FORBIDDEN", f"this needs the {needed} role")
        return p

    return dependency


async def staff_on_socket(conn: HTTPConnection, *roles: StaffRole) -> Principal:
    """The same staff check as ``require_staff``, for WebSocket routes (raises ``ApiError``)."""
    p = await current_principal(conn)
    if p.kind == "anonymous":
        raise ApiError(401, "AUTH_REQUIRED", "sign in first")
    if p.kind == "participant":
        raise ApiError(403, "ROLE_FORBIDDEN", "participants cannot do this")
    if roles and not any(p.has(r) for r in roles):
        raise ApiError(403, "ROLE_FORBIDDEN", "this needs another role")
    return p


async def _scenario_of(request: Request, inv_id: str) -> str:
    async with request.app.state.db.read() as session:
        sid = (
            await session.execute(
                select(InvestigationRow.scenario_id).where(InvestigationRow.id == inv_id)
            )
        ).scalar_one_or_none()
    if sid is None:
        raise not_found("investigation")
    return str(sid)


async def authorize_participant(request: Request, inv_id: str, participant_id: str) -> Principal:
    """Allow an operator, or the participant themself holding a token for this investigation."""
    p = await current_principal(request)
    if p.kind in ("open", "automation") or p.has(StaffRole.OPERATOR):
        return p
    if p.kind == "participant":
        if p.participant_id != participant_id:
            raise ApiError(403, "PARTICIPANT_FORBIDDEN", "this token is for another participant")
        if p.scenario_id != await _scenario_of(request, inv_id):
            raise ApiError(403, "PARTICIPANT_FORBIDDEN", "this token is for another investigation")
        return p
    if p.kind == "anonymous":
        raise ApiError(401, "AUTH_REQUIRED", "sign in or use your join link")
    raise ApiError(403, "ROLE_FORBIDDEN", "this needs the operator role or the participant's link")


async def authorize_read(request: Request, inv_id: str) -> Principal:
    """Any staff member, or a participant of this investigation."""
    p = await current_principal(request)
    if p.kind == "anonymous":
        raise ApiError(401, "AUTH_REQUIRED", "sign in or use your join link")
    if p.kind == "participant" and p.scenario_id != await _scenario_of(request, inv_id):
        raise ApiError(403, "PARTICIPANT_FORBIDDEN", "this token is for another investigation")
    return p


def participant_public_key(signing_key_b64: str) -> Ed25519PublicKey:
    return private_key_from_b64(signing_key_b64).public_key()
