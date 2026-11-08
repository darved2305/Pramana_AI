# No future annotations: FastAPI resolves dependency annotations at runtime.
"""The workspace home: ordered modules with the reason each one is shown."""

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from pramana_contracts import WorkspaceHome

from ..account_rows import PreferenceRow
from ..db import Database
from ..home import load_facts, plan_home
from ..tenant_routes import OrganizationRoute

router = APIRouter(prefix="/v1/orgs/{org}", tags=["home"], route_class=OrganizationRoute)


@router.get("/home")
async def home(org: str, request: Request, response: Response) -> WorkspaceHome:
    access = request.state.organization
    principal = request.state.principal
    db: Database = request.app.state.db
    async with db.read() as session:
        layout = await session.scalar(
            select(PreferenceRow.home_layout).where(PreferenceRow.user_id == principal.id)
        )
        facts = await load_facts(
            session,
            access.organization.id,
            display_name=principal.display_name,
            roles=frozenset(access.roles),
            layout=layout or {},
        )
    response.headers["Cache-Control"] = "private, no-store"
    return plan_home(facts)
