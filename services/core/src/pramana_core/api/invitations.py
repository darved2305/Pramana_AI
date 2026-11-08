# No future annotations: FastAPI resolves dependency annotations at runtime.
"""Invite people into a workspace, and accept an invitation."""

import uuid

from fastapi import APIRouter, Request, Response

from pramana_contracts import (
    AcceptInvitation,
    CreateInvitation,
    InvitationAccepted,
    InvitationCreated,
    InvitationView,
)

from .. import ids
from ..errors import not_found
from ..idempotency import IdempotencyRoute, idempotent
from ..invitations import Invitations, invitation_view
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
async def list_invitations(org: str, request: Request, response: Response) -> list[InvitationView]:
    access = request.state.organization
    if not set(MANAGERS) & set(access.roles):
        return []  # members who cannot invite do not see who else was invited
    rows = await _service(request, response).listing(access.organization.id)
    return [invitation_view(row, name) for row, name in rows]


@router.post("", status_code=201)
@idempotent("org", roles=MANAGERS)
async def create_invitation(
    org: str, body: CreateInvitation, request: Request, response: Response
) -> InvitationCreated:
    """Returns the link once. Share it with the person; it works for their email only."""
    access = request.state.organization
    row, token = await _service(request, response).create(
        access.organization.id, request.state.principal, body
    )
    name = request.state.principal.display_name
    return InvitationCreated(invitation=invitation_view(row, name), accept_path=f"/invite/{token}")


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
