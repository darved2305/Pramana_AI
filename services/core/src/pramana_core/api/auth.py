# No ``from __future__ import annotations``: FastAPI resolves dependency annotations at runtime.
"""Console sign-in (``/v1/auth``): server-side sessions in an httpOnly cookie."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request, Response

from pramana_contracts import AuthSession, LoginRequest, StaffRole

from ..auth.deps import CSRF_HEADER, SESSION_COOKIE, current_principal
from ..auth.service import AuthService, Principal
from ..errors import ApiError
from ..settings import Settings

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _view(p: Principal, method: str) -> AuthSession:
    return AuthSession(
        user_id=p.id,
        display_name=p.display_name,
        email=p.email,
        roles=sorted((StaffRole(r) for r in p.roles), key=lambda r: r.value),
        expires_at=p.expires_at or datetime.now(UTC) + timedelta(days=365),
        method=method,
    )


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response) -> AuthSession:
    """Sign in. Sets the ``pramana_session`` cookie (httpOnly, SameSite=Lax)."""
    if request.headers.get(CSRF_HEADER) != "1":
        # Blocks login CSRF: a cross-site form cannot add this header.
        raise ApiError(403, "CSRF_HEADER_MISSING", "send X-Pramana-CSRF: 1 with this request")
    auth: AuthService = request.app.state.auth
    cfg: Settings = request.app.state.settings
    token, principal = await auth.login(body.email, body.password)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=cfg.session_ttl_s,
        httponly=True,
        samesite="lax",
        secure=cfg.secure_cookies,
        path="/",
    )
    return _view(principal, "session")


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        if request.headers.get(CSRF_HEADER) != "1":
            raise ApiError(403, "CSRF_HEADER_MISSING", "send X-Pramana-CSRF: 1 with this request")
        auth: AuthService = request.app.state.auth
        await auth.logout(token)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/session")
async def get_session(request: Request) -> AuthSession:
    """Who is signed in. ``401 AUTH_REQUIRED`` when nobody is."""
    p = await current_principal(request)
    if p.kind in ("anonymous", "participant"):
        raise ApiError(401, "AUTH_REQUIRED", "not signed in")
    return _view(p, "session" if p.kind == "user" else p.kind)
