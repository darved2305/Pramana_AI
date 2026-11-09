# No future annotations: FastAPI resolves dependency annotations at runtime.
"""Verified domain settings and requests to join a workspace."""

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, BackgroundTasks, Query, Request, Response

from pramana_contracts import (
    CreateDomain,
    CursorPage,
    JoinRequestCreated,
    JoinRequestDecision,
    JoinRequestView,
    OrganizationDomain,
    RequestJoin,
    UpdateDomainPolicy,
)

from .. import ids
from ..cursors import CursorCodec
from ..domain_joins import MANAGERS, DomainJoins
from ..errors import not_found
from ..idempotency import IdempotencyRoute, idempotent
from ..org_access import require_user
from ..tenant_routes import OrganizationRoute

org_router = APIRouter(
    prefix="/v1/orgs/{org}", tags=["workspace domains"], route_class=OrganizationRoute
)
user_router = APIRouter(prefix="/v1", tags=["workspace joins"], route_class=IdempotencyRoute)


def _service(request: Request) -> DomainJoins:
    return cast(DomainJoins, request.app.state.domain_joins)


def _request_id(value: str) -> uuid.UUID:
    try:
        return ids.decode("join", value)
    except ValueError as exc:
        raise not_found("join request") from exc


@org_router.get("/domains")
async def list_domains(request: Request, response: Response) -> list[OrganizationDomain]:
    access = request.state.organization
    if not set(MANAGERS).intersection(access.roles):
        from ..errors import ApiError

        raise ApiError(403, "ROLE_FORBIDDEN", "only workspace owners and admins can manage domains")
    response.headers["Cache-Control"] = "private, no-store"
    return await _service(request).list_domains(access.organization.id)


@org_router.post("/domains", status_code=201)
@idempotent("org", roles=MANAGERS, verified=True)
async def add_domain(
    org: str, body: CreateDomain, request: Request, response: Response
) -> OrganizationDomain:
    access = request.state.organization
    result = await _service(request).add_domain(access.organization.id, access.principal, body)
    response.headers["Cache-Control"] = "private, no-store"
    return result


@org_router.post("/domains/{domain}/verify")
@idempotent("org", roles=MANAGERS, verified=True)
async def verify_domain(
    org: str, domain: str, request: Request, response: Response
) -> OrganizationDomain:
    access = request.state.organization
    result = await _service(request).verify_domain(access.organization.id, domain, access.principal)
    response.headers["Cache-Control"] = "private, no-store"
    return result


@org_router.patch("/domains/{domain}")
@idempotent("org", roles=MANAGERS, verified=True)
async def set_domain_policy(
    org: str,
    domain: str,
    body: UpdateDomainPolicy,
    request: Request,
    response: Response,
) -> OrganizationDomain:
    access = request.state.organization
    result = await _service(request).set_policy(
        access.organization.id, domain, access.principal, body.join_policy
    )
    response.headers["Cache-Control"] = "private, no-store"
    return result


@org_router.delete("/domains/{domain}", status_code=204)
@idempotent("org", roles=MANAGERS, verified=True)
async def remove_domain(org: str, domain: str, request: Request, response: Response) -> Response:
    access = request.state.organization
    await _service(request).remove_domain(access.organization.id, domain, access.principal)
    return Response(status_code=204)


@org_router.get("/join-requests")
async def list_join_requests(
    org: str,
    request: Request,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
) -> CursorPage[JoinRequestView]:
    access = request.state.organization
    response.headers["Cache-Control"] = "private, no-store"
    items, next_cursor = await _service(request).list_join_requests(
        access.organization.id,
        request.state.principal,
        limit=limit,
        cursor=cursor,
        codec=cast(CursorCodec, request.app.state.cursor_codec),
    )
    return CursorPage[JoinRequestView](items=items, limit=limit, next_cursor=next_cursor)


@org_router.post("/join-requests/{request_id}/approve")
@idempotent("org", roles=MANAGERS, verified=True)
async def approve_join_request(
    org: str,
    request_id: str,
    body: JoinRequestDecision,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
) -> JoinRequestView:
    access = request.state.organization
    result = await _service(request).decide_request(
        access.organization.id, _request_id(request_id), access.principal, body
    )
    background_tasks.add_task(request.app.state.email_relay.drain)
    response.headers["Cache-Control"] = "private, no-store"
    return result


@org_router.post("/join-requests/{request_id}/decline")
@idempotent("org", roles=MANAGERS, verified=True)
async def decline_join_request(
    org: str,
    request_id: str,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
) -> JoinRequestView:
    access = request.state.organization
    result = await _service(request).decide_request(
        access.organization.id, _request_id(request_id), access.principal, None
    )
    background_tasks.add_task(request.app.state.email_relay.drain)
    response.headers["Cache-Control"] = "private, no-store"
    return result


@user_router.post("/join-requests", status_code=201)
@idempotent("user", verified=True)
async def request_to_join(
    body: RequestJoin,
    request: Request,
    response: Response,
    background_tasks: BackgroundTasks,
) -> JoinRequestCreated:
    principal = await require_user(request, verified=True)
    try:
        org_id = ids.decode("org", body.organization_id)
    except ValueError as exc:
        raise not_found("workspace") from exc
    result = await _service(request).request_join(principal, org_id)
    background_tasks.add_task(request.app.state.email_relay.drain)
    response.headers["Cache-Control"] = "private, no-store"
    return result


@user_router.post("/join-requests/{request_id}/cancel", status_code=204)
@idempotent("user", verified=True)
async def cancel_join_request(request_id: str, request: Request) -> Response:
    principal = await require_user(request, verified=True)
    await _service(request).cancel_request(principal, _request_id(request_id))
    return Response(status_code=204)
