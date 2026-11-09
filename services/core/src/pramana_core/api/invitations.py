# No future annotations: FastAPI resolves dependency annotations at runtime.
"""Invite people into a workspace, and accept an invitation."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response

from pramana_contracts import (
    AcceptInvitation,
    AcceptPendingInvitation,
    CreateInvitation,
    CursorPage,
    InvitationAccepted,
    InvitationCreated,
    InvitationView,
)

from .. import ids
from ..cursors import CursorCodec
from ..errors import not_found
from ..idempotency import IdempotencyRoute, idempotent
from ..invitations import Invitations, email_invitation, invitation_view
from ..org_access import require_user
from ..tenant_routes import OrganizationRoute

MANAGERS = ("owner", "admin")
router = APIRouter(
    prefix="/v1/orgs/{org}/invitations", tags=["invitations"], route_class=OrganizationRoute
)
accept_router = APIRouter(
    prefix="/v1/invitations", tags=["invitations"], route_class=IdempotencyRoute
)


def _service(request: Request, response: Response) -> Invitations:
    response.headers["Cache-Control"] = "private, no-store"
    service: Invitations = request.app.state.invitations
    return service


@router.get("")
async def list_invitations(
    org: str,
    request: Request,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
) -> CursorPage[InvitationView]:
    access = request.state.organization
    codec: CursorCodec = request.app.state.cursor_codec
    if not set(MANAGERS) & set(access.roles):
        return CursorPage[InvitationView](items=[], limit=limit, next_cursor=None)
    rows, next_cursor = await _service(request, response).listing(
        access.organization.id, limit, cursor, codec
    )
    return CursorPage[InvitationView](
        items=[invitation_view(row, name) for row, name in rows],
        limit=limit,
        next_cursor=next_cursor,
    )


@router.post("", status_code=201)
@idempotent("org", roles=MANAGERS)
async def create_invitation(
    org: str, body: CreateInvitation, request: Request, response: Response
) -> InvitationCreated:
    """Returns the link once, and emails it when Gmail is set up. It works for their email only."""
    access = request.state.organization
    row, token = await _service(request, response).create(
        access.organization.id, request.state.principal, body
    )
    name = request.state.principal.display_name
    accept_path = f"/invite/{token}"
    delivery = await email_invitation(
        request.app.state.mailer,
        request.app.state.settings.invitation_link_base,
        row,
        access.organization.name,
        name,
        accept_path,
    )
    return InvitationCreated(
        invitation=invitation_view(row, name), accept_path=accept_path, email_delivery=delivery
    )


@router.post("/{invite_id}/revoke", status_code=204)
@idempotent("org", roles=MANAGERS)
async def revoke_invitation(
    org: str, invite_id: str, request: Request, response: Response
) -> Response:
    try:
        value: uuid.UUID = ids.decode("invite", invite_id)
    except ValueError as exc:
        raise not_found("invitation") from exc
    access = request.state.organization
    await _service(request, response).revoke(access.organization.id, request.state.principal, value)
    return Response(status_code=204)


@accept_router.post("/accept")
@idempotent("user", verified=True)
async def accept_invitation(
    body: AcceptInvitation, request: Request, response: Response
) -> InvitationAccepted:
    principal = await require_user(request, verified=True)
    return await _service(request, response).accept(principal, body.token)


@accept_router.post("/accept-pending")
@idempotent("user", verified=True)
async def accept_pending_invitation(
    body: AcceptPendingInvitation, request: Request, response: Response
) -> InvitationAccepted:
    """Accept an invitation listed in ``/v1/me``, sent to this verified address."""
    principal = await require_user(request, verified=True)
    return await _service(request, response).accept_pending(
        principal, body.organization_id, body.invitation_id
    )
