"""The account/organization authorization boundary, before any tenant query or replay."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import select

from . import ids
from .auth.deps import current_principal
from .auth.service import Principal
from .db import Database, MembershipRow, OrganizationRow, acting_for
from .errors import ApiError, not_found


async def require_user(request: Request, *, verified: bool = False) -> Principal:
    principal = await current_principal(request)
    if principal.kind != "user":
        raise ApiError(401, "AUTH_REQUIRED", "sign in with your own account")
    if verified and not principal.email_verified:
        raise ApiError(
            403, "EMAIL_VERIFICATION_REQUIRED", "verify your email before creating a workspace"
        )
    return principal


@dataclass(frozen=True)
class OrganizationAccess:
    organization: OrganizationRow
    roles: tuple[str, ...]
    principal: Principal


async def require_organization(
    request: Request,
    principal: Principal,
    roles: tuple[str, ...] = (),
    *,
    include_deleted: bool = False,
) -> OrganizationAccess:
    value = str(request.path_params.get("org", ""))
    try:
        condition = (
            OrganizationRow.id == ids.decode("org", value)
            if value.startswith("org_")
            else OrganizationRow.slug == value
        )
    except ValueError as exc:
        raise not_found("organization") from exc
    db: Database = request.app.state.db
    with acting_for(None, principal.id):
        async with db.read() as session:
            found = (
                await session.execute(
                    select(OrganizationRow, MembershipRow.roles)
                    .join(MembershipRow, MembershipRow.org_id == OrganizationRow.id)
                    .where(
                        condition,
                        MembershipRow.user_id == principal.id,
                        MembershipRow.status == "active",
                        *(() if include_deleted else (OrganizationRow.deleted_at.is_(None),)),
                    )
                )
            ).one_or_none()
    if found is None:
        raise not_found("organization")
    organization, held_roles = found
    if roles and not set(roles).intersection(held_roles):
        raise ApiError(403, "ROLE_FORBIDDEN", "your workspace role does not allow this action")
    return OrganizationAccess(organization, tuple(held_roles), principal)


async def participant_organization(request: Request, principal: Principal) -> OrganizationAccess:
    """Resolve only the organization signed into a participant's token, never a membership."""
    if principal.kind != "participant" or not principal.organization_id or not principal.token_id:
        raise not_found("organization")
    try:
        org_id = ids.decode("org", principal.organization_id)
        value = str(request.path_params.get("org", ""))
        condition = (
            OrganizationRow.id == ids.decode("org", value)
            if value.startswith("org_")
            else OrganizationRow.slug == value
        )
    except ValueError as exc:
        raise not_found("organization") from exc
    db: Database = request.app.state.db
    with acting_for(org_id, actor=f"participant:{principal.token_id}"):
        async with db.read() as session:
            org = await session.scalar(
                select(OrganizationRow).where(
                    OrganizationRow.id == org_id,
                    condition,
                    OrganizationRow.deleted_at.is_(None),
                )
            )
    if org is None:
        raise not_found("organization")
    return OrganizationAccess(org, (), principal)
