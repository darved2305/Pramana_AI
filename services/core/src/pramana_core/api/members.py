# No future annotations: FastAPI resolves dependency annotations at runtime.
"""Who has an account in this workspace, their roles, and changing or removing them.

Rules: owners and admins manage members; only an owner gives or takes away the owner role; the
last owner can neither lose that role nor be removed, so a workspace always has an owner; anyone
may leave unless they are the last owner. Every change is written to the audit log, and access
ends at once because every request re-checks the membership.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Path, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pramana_contracts import OrganizationRole, UpdateMemberRoles, WorkspaceMember

from .. import ids
from ..db import AuditLogRow, Database, MembershipRow, UserRow
from ..errors import ApiError, not_found
from ..idempotency import idempotent
from ..tenant_routes import OrganizationRoute

MANAGERS = ("owner", "admin")
EVERYONE = ("owner", "admin", "operator", "approver", "viewer")
LAST_OWNER = "a workspace needs an owner; make someone else owner first"
MemberId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_.:-]{1,32}$")]
router = APIRouter(prefix="/v1/orgs/{org}", tags=["members"], route_class=OrganizationRoute)


def _view(m: MembershipRow, name: str, email: str, admin: bool, me: str) -> WorkspaceMember:
    return WorkspaceMember.model_validate(
        {
            "id": m.user_id,
            "display_name": name,
            "email": email if admin or m.user_id == me else None,
            "roles": [OrganizationRole(r) for r in sorted(m.roles)],
            "status": m.status,
            "joined_at": m.created_at,
            "you": m.user_id == me,
        }
    )


@router.get("/members")
async def members(org: str, request: Request, response: Response) -> list[WorkspaceMember]:
    access = request.state.organization
    principal = request.state.principal
    admin = bool(set(MANAGERS) & set(access.roles))
    db: Database = request.app.state.db
    async with db.read() as session:
        rows = (
            await session.execute(
                select(MembershipRow, UserRow.display_name, UserRow.email)
                .join(UserRow, UserRow.id == MembershipRow.user_id)
                .where(MembershipRow.org_id == access.organization.id)
                .order_by(MembershipRow.created_at, MembershipRow.user_id)
            )
        ).all()
    response.headers["Cache-Control"] = "private, no-store"
    return [_view(m, name, email, admin, principal.id) for m, name, email in rows]


async def _owners(session: AsyncSession, org_id: uuid.UUID) -> int:
    # Lock every owner row, so two owners demoting each other at once cannot both succeed.
    rows = await session.scalars(
        select(MembershipRow.user_id)
        .where(
            MembershipRow.org_id == org_id,
            MembershipRow.status == "active",
            func.array_position(MembershipRow.roles, "owner").is_not(None),
        )
        .with_for_update()
    )
    return len(rows.all())


async def _locked(session: AsyncSession, org_id: uuid.UUID, user_id: str) -> MembershipRow:
    member = await session.scalar(
        select(MembershipRow)
        .where(MembershipRow.org_id == org_id, MembershipRow.user_id == user_id)
        .with_for_update()
    )
    if member is None:
        raise not_found("member")
    return member


def _audit(
    org_id: uuid.UUID, actor: str, action: str, target: str, details: dict[str, Any]
) -> AuditLogRow:
    return AuditLogRow(
        id=ids.uuid7(),
        org_id=org_id,
        actor_kind="user",
        actor_id=actor,
        action=action,
        target_kind="membership",
        target_id=target,
        details=details,
    )


@router.patch("/members/{member_id}")
@idempotent("org", roles=MANAGERS)
async def update_member(
    org: str, member_id: MemberId, body: UpdateMemberRoles, request: Request, response: Response
) -> WorkspaceMember:
    access = request.state.organization
    principal = request.state.principal
    org_id = access.organization.id
    db: Database = request.app.state.db
    async with db.transaction() as session:
        owners = await _owners(session, org_id)
        member = await _locked(session, org_id, member_id)
        before, after = set(member.roles), {str(r) for r in body.roles}
        if ("owner" in before) != ("owner" in after) and "owner" not in access.roles:
            raise ApiError(403, "OWNER_ONLY", "only an owner can give or take away the owner role")
        if "owner" in before and "owner" not in after and owners <= 1:
            raise ApiError(409, "LAST_OWNER", LAST_OWNER)
        member.roles = sorted(after)
        session.add(
            _audit(
                org_id,
                principal.id,
                "membership.roles_changed",
                member_id,
                {"from": sorted(before), "to": sorted(after)},
            )
        )
        await session.flush()
        user = await session.get(UserRow, member_id)
        name, email = (user.display_name, user.email) if user else ("", "")
    response.headers["Cache-Control"] = "private, no-store"
    return _view(member, name, email, True, principal.id)


@router.post("/members/{member_id}/remove", status_code=204)
@idempotent("org", roles=EVERYONE)
async def remove_member(
    org: str, member_id: MemberId, request: Request, response: Response
) -> Response:
    """Owners and admins remove anyone; everyone may remove themselves (leave)."""
    access = request.state.organization
    principal = request.state.principal
    org_id = access.organization.id
    leaving = member_id == principal.id
    if not leaving and not set(MANAGERS) & set(access.roles):
        raise ApiError(403, "ROLE_FORBIDDEN", "your workspace role does not allow this action")
    db: Database = request.app.state.db
    async with db.transaction() as session:
        owners = await _owners(session, org_id)
        member = await _locked(session, org_id, member_id)
        if "owner" in member.roles:
            if not leaving and "owner" not in access.roles:
                raise ApiError(403, "OWNER_ONLY", "only an owner can remove an owner")
            if owners <= 1:
                raise ApiError(409, "LAST_OWNER", LAST_OWNER)
        roles = sorted(member.roles)
        await session.delete(member)
        session.add(
            _audit(
                org_id,
                principal.id,
                "membership.left" if leaving else "membership.removed",
                member_id,
                {"roles": roles},
            )
        )
    return Response(status_code=204)
