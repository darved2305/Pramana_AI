# No ``from __future__ import annotations``: FastAPI resolves dependency annotations at runtime.
"""Console sign-in (``/v1/auth``): server-side sessions in an httpOnly cookie."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response
from fastapi.responses import RedirectResponse

from pramana_contracts import AuthSession, LoginRequest, SessionDevice, StaffRole

from ..auth.deps import CSRF_HEADER, current_principal, require_staff
from ..auth.google import AccountDisabledError, AccountExistsError, GoogleSignIn
from ..auth.oidc import OidcError
from ..auth.service import AuthService, Principal, token_hash
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
        email_verified=p.email_verified,
    )


def _session_cookie(response: Response, cfg: Settings, token: str) -> None:
    response.set_cookie(
        cfg.session_cookie_name,
        token,
        max_age=cfg.session_ttl_s,
        httponly=True,
        samesite="lax",
        secure=cfg.secure_cookies,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    if cfg.secure_cookies:
        response.delete_cookie(
            "pramana_session", path="/", secure=True, httponly=True, samesite="lax"
        )


def _redirect(path: str) -> RedirectResponse:
    return RedirectResponse(
        path,
        status_code=302,
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        },
    )


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response) -> AuthSession:
    """Sign in. Sets the ``pramana_session`` cookie (httpOnly, SameSite=Lax)."""
    if request.headers.get(CSRF_HEADER) != "1":
        # Blocks login CSRF: a cross-site form cannot add this header.
        raise ApiError(403, "CSRF_HEADER_MISSING", "send X-Pramana-CSRF: 1 with this request")
    auth: AuthService = request.app.state.auth
    cfg: Settings = request.app.state.settings
    token, principal = await auth.login(
        body.email,
        body.password,
        old_token=request.cookies.get(cfg.session_cookie_name),
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )
    _session_cookie(response, cfg, token)
    return _view(principal, "session")


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> None:
    cfg: Settings = request.app.state.settings
    if request.headers.get(CSRF_HEADER) != "1":
        raise ApiError(403, "CSRF_HEADER_MISSING", "send X-Pramana-CSRF: 1 with this request")
    token = request.cookies.get(cfg.session_cookie_name)
    if token:
        if request.headers.get(CSRF_HEADER) != "1":
            raise ApiError(403, "CSRF_HEADER_MISSING", "send X-Pramana-CSRF: 1 with this request")
        auth: AuthService = request.app.state.auth
        await auth.logout(token)
    for cookie in {
        cfg.session_cookie_name,
        cfg.auth_flow_cookie_name,
        "pramana_session",
        "pramana_auth",
    }:
        response.delete_cookie(
            cookie, path="/", secure=cfg.secure_cookies, httponly=True, samesite="lax"
        )
    response.headers["Clear-Site-Data"] = '"cache", "cookies", "storage"'
    response.headers["Cache-Control"] = "no-store"


@router.get("/session")
async def get_session(request: Request, response: Response) -> AuthSession:
    """Who is signed in. ``401 AUTH_REQUIRED`` when nobody is."""
    p = await current_principal(request)
    if p.kind in ("anonymous", "participant"):
        raise ApiError(401, "AUTH_REQUIRED", "not signed in")
    response.headers["Cache-Control"] = "no-store"
    return _view(p, "session" if p.kind == "user" else p.kind)


@router.get("/google/start")
async def google_start(
    request: Request,
    next_path: Annotated[str, Query(alias="next", max_length=2048)] = "/app",
    login_hint: Annotated[str | None, Query(max_length=254)] = None,
    switch_account: bool = False,
) -> RedirectResponse:
    cfg: Settings = request.app.state.settings
    google: GoogleSignIn = request.app.state.google_sign_in
    try:
        cookie, url = await google.start(
            next_path,
            request.cookies.get(cfg.auth_flow_cookie_name),
            request.cookies.get(cfg.session_cookie_name),
            login_hint=login_hint,
            switch_account=switch_account,
        )
    except (OidcError, ValueError):
        return _redirect("/login?error=sign_in_unavailable")
    response = _redirect(url)
    response.set_cookie(
        cfg.auth_flow_cookie_name,
        cookie,
        max_age=600,
        httponly=True,
        secure=cfg.secure_cookies,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/google/callback")
async def google_callback(request: Request) -> RedirectResponse:
    cfg: Settings = request.app.state.settings
    google: GoogleSignIn = request.app.state.google_sign_in
    query = request.query_params
    try:
        flow = await google.consume(
            request.cookies.get(cfg.auth_flow_cookie_name), query.get("state")
        )
        if any(len(query.getlist(key)) > 1 for key in ("state", "code", "error")):
            raise OidcError("ambiguous callback")
        if query.get("error"):
            error = "cancelled" if query["error"] == "access_denied" else "sign_in_failed"
            response = _redirect(f"/login?error={error}")
        else:
            code = query.get("code")
            if not code or len(code) > 4096:
                raise OidcError("missing authorization code")
            token, principal = await google.finish(
                flow,
                code,
                request.cookies.get(cfg.session_cookie_name),
                request.headers.get("user-agent"),
            )
            await request.app.state.domain_joins.auto_join_on_sign_in(principal)
            response = _redirect(flow.next_path)
            _session_cookie(response, cfg, token)
    except AccountExistsError:
        response = _redirect("/login?error=account_exists")
    except AccountDisabledError:
        response = _redirect("/login?error=account_disabled")
    except OidcError:
        response = _redirect("/login?error=sign_in_failed")
    response.delete_cookie(
        cfg.auth_flow_cookie_name,
        path="/",
        secure=cfg.secure_cookies,
        httponly=True,
        samesite="lax",
    )
    return response


async def _signed_in_user(request: Request) -> Principal:
    principal = await require_staff()(request)
    if principal.kind != "user":
        raise ApiError(403, "AUTH_USER_REQUIRED", "sign in with your own account")
    return principal


@router.get("/devices")
async def devices(request: Request, response: Response) -> list[SessionDevice]:
    principal = await _signed_in_user(request)
    auth: AuthService = request.app.state.auth
    cfg: Settings = request.app.state.settings
    current = token_hash(request.cookies.get(cfg.session_cookie_name, ""))
    response.headers["Cache-Control"] = "no-store"
    return [
        SessionDevice(
            id=row.token_hash,
            current=row.token_hash == current,
            auth_method=row.auth_method,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            idle_expires_at=row.idle_expires_at,
            absolute_expires_at=row.absolute_expires_at,
            user_agent=row.user_agent,
        )
        for row in await auth.devices(principal.id)
    ]


@router.post("/devices/revoke-others", status_code=204)
async def revoke_other_devices(request: Request) -> None:
    principal = await _signed_in_user(request)
    cfg: Settings = request.app.state.settings
    auth: AuthService = request.app.state.auth
    await auth.revoke_others(principal.id, request.cookies[cfg.session_cookie_name])


@router.delete("/devices/{device_id}", status_code=204)
async def revoke_device(
    request: Request, device_id: Annotated[str, Path(pattern=r"^[a-f0-9]{64}$")]
) -> None:
    principal = await _signed_in_user(request)
    auth: AuthService = request.app.state.auth
    await auth.revoke_device(principal.id, device_id)
