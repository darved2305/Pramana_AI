# No future annotations: FastAPI resolves dependency annotations at runtime.
"""Describe a site, generate and check its model, publish a version (organization scoped)."""

import uuid

from fastapi import APIRouter, Header, Request, Response

from pramana_contracts import (
    EquipmentTypeView,
    ParticipantSpec,
    SaveDraft,
    SiteModelDraft,
    SiteModelSummary,
    SiteTemplateView,
)
from pramana_domain.catalog import equipment_types, templates

from .. import ids
from ..errors import not_found
from ..idempotency import idempotent
from ..org_access import require_user
from ..site_builder import SiteBuilder, draft_etag, draft_view, summary
from ..tenant_routes import OrganizationRoute

EDITORS = ("operator", "owner", "admin")
library = APIRouter(prefix="/v1/library", tags=["site builder"])
router = APIRouter(
    prefix="/v1/orgs/{org}/sites/{site_id}/draft",
    tags=["site builder"],
    route_class=OrganizationRoute,
)


@library.get("/equipment")
async def equipment(request: Request) -> list[EquipmentTypeView]:
    """Equipment types a site author can choose from, with their faults, checks and repairs."""
    await require_user(request)
    return [EquipmentTypeView.model_validate(t) for t in equipment_types()]


@library.get("/templates")
async def site_templates(request: Request) -> list[SiteTemplateView]:
    """Starter site descriptions to copy into a draft and edit."""
    await require_user(request)
    return [SiteTemplateView.model_validate(t) for t in templates().values()]


def _id(prefix: str, value: str) -> uuid.UUID:
    try:
        return ids.decode(prefix, value)
    except ValueError as exc:
        raise not_found("draft" if prefix == "model" else "site") from exc


def _builder(request: Request, response: Response) -> SiteBuilder:
    response.headers["Cache-Control"] = "private, no-store"
    builder: SiteBuilder = request.app.state.site_builder
    return builder


@router.get("")
async def get_draft(org: str, site_id: str, request: Request, response: Response) -> SiteModelDraft:
    row = await _builder(request, response).get(_id("site", site_id))
    response.headers["ETag"] = draft_etag(row)
    return draft_view(row)


@router.post(
    "",
    openapi_extra={
        "parameters": [
            {"name": "If-Match", "in": "header", "required": False, "schema": {"type": "string"}}
        ],
        "responses": {
            "412": {"description": "The draft changed in another tab"},
            "422": {"description": "The description has problems; details.problems lists them"},
            "428": {"description": "Replacing a draft needs the version being edited"},
        },
    },
)
@idempotent("org", roles=EDITORS)
async def save_draft(
    org: str,
    site_id: str,
    body: SaveDraft,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> SiteModelDraft:
    """Start a draft from a template or description, or replace the current one."""
    row = await _builder(request, response).save(_id("site", site_id), body, if_match)
    response.headers["ETag"] = draft_etag(row)
    return draft_view(row)


@router.post("/{model_id}/health")
@idempotent("org", roles=EDITORS)
async def check_draft(
    org: str,
    site_id: str,
    model_id: str,
    request: Request,
    response: Response,
    people: list[ParticipantSpec] | None = None,
) -> SiteModelDraft:
    """Judge the generated model against these people, or one person per role."""
    row = await _builder(request, response).health(
        _id("site", site_id), _id("model", model_id), people
    )
    response.headers["ETag"] = draft_etag(row)
    return draft_view(row)


@router.post("/{model_id}/publish")
@idempotent("org", roles=EDITORS)
async def publish_draft(
    org: str, site_id: str, model_id: str, request: Request, response: Response
) -> SiteModelSummary:
    """Publish the checked draft as the site's current, immutable version."""
    row = await _builder(request, response).publish(_id("site", site_id), _id("model", model_id))
    return summary(row)


@router.post("/{model_id}/discard", status_code=204)
@idempotent("org", roles=EDITORS)
async def discard_draft(
    org: str, site_id: str, model_id: str, request: Request, response: Response
) -> Response:
    await _builder(request, response).discard(_id("site", site_id), _id("model", model_id))
    return Response(status_code=204)
