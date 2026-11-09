# No future annotations: FastAPI resolves dependency annotations at runtime.
"""The workspace home: ordered modules with the reason each one is shown."""

from typing import cast

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from pramana_contracts import WorkspaceHome

from ..account_rows import PreferenceRow
from ..cursors import CursorCodec
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
            vault=request.app.state.vault,
        )
    response.headers["Cache-Control"] = "private, no-store"
    result = plan_home(facts)
    if {"owner", "admin"}.intersection(principal.roles):
        # The home shows the first page only; the full history is paged on its own route.
        requests, _ = await request.app.state.domain_joins.list_join_requests(
            access.organization.id,
            principal,
            limit=10,
            cursor=None,
            codec=cast(CursorCodec, request.app.state.cursor_codec),
        )
        result = result.model_copy(update={"join_requests": requests})
    return result
