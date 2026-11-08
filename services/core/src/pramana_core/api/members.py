# No future annotations: FastAPI resolves dependency annotations at runtime.
"""Who has an account in this workspace, and with which roles."""

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from pramana_contracts import OrganizationRole, WorkspaceMember

from ..db import Database, MembershipRow, UserRow
from ..tenant_routes import OrganizationRoute

router = APIRouter(prefix="/v1/orgs/{org}", tags=["members"], route_class=OrganizationRoute)


@router.get("/members")
async def members(org: str, request: Request, response: Response) -> list[WorkspaceMember]:
    access = request.state.organization
    principal = request.state.principal
    admin = bool({"owner", "admin"} & set(access.roles))
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
    return [
        WorkspaceMember(
            display_name=name,
            email=email if admin or m.user_id == principal.id else None,
            roles=[OrganizationRole(r) for r in sorted(m.roles)],
            status=m.status,
            joined_at=m.created_at,
            you=m.user_id == principal.id,
        )
        for m, name, email in rows
    ]
