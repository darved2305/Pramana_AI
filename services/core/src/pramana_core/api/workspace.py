"""Workspace export, reversible deletion, and restore."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import cast

from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse

from pramana_contracts import DeleteOrganization, OrganizationDeletion, OrganizationSummary

from ..accounts import organization_view
from ..errors import ApiError
from ..idempotency import idempotent
from ..tenant_routes import OrganizationRoute, deleted_workspace_access
from ..workspace_lifecycle import WorkspaceLifecycle

router = APIRouter(prefix="/v1/orgs/{org}", tags=["workspace"], route_class=OrganizationRoute)


def _lifecycle(request: Request) -> WorkspaceLifecycle:
    return cast(WorkspaceLifecycle, request.app.state.workspace_lifecycle)


def _owner(request: Request) -> tuple[str, tuple[str, ...]]:
    access = request.state.organization
    if "owner" not in access.roles:
        raise ApiError(403, "OWNER_ONLY", "only a workspace owner can do this")
    return request.state.principal.id, access.roles


@router.delete("")
@deleted_workspace_access("delete")
@idempotent("org", roles=("owner",))
async def delete_workspace(
    org: str, body: DeleteOrganization, request: Request
) -> OrganizationDeletion:
    principal_id, _ = _owner(request)
    access = request.state.organization
    return await _lifecycle(request).delete(access.organization.id, principal_id, body)


@router.get("/export")
@deleted_workspace_access("export")
async def export_workspace(org: str, request: Request) -> StreamingResponse:
    principal_id, _ = _owner(request)
    access = request.state.organization
    archive = await _lifecycle(request).export(access.organization.id, principal_id)
    filename = f"{access.organization.slug}-export-{datetime.now(UTC):%Y%m%d}.zip"

    def chunks() -> Iterator[bytes]:
        try:
            while chunk := archive.read(64 * 1024):
                yield chunk
        finally:
            archive.close()

    return StreamingResponse(
        chunks(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/restore")
@deleted_workspace_access("restore")
@idempotent("org", roles=("owner",))
async def restore_workspace(org: str, request: Request, response: Response) -> OrganizationSummary:
    principal_id, roles = _owner(request)
    access = request.state.organization
    row = await _lifecycle(request).restore(access.organization.id, principal_id)
    response.headers["Cache-Control"] = "private, no-store"
    return organization_view(row, roles)
