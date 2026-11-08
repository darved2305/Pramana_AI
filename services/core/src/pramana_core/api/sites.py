# No future annotations: FastAPI resolves dependency annotations at runtime.
"""Saved sites and their published model versions, scoped to an active membership."""

import hashlib
import uuid

from fastapi import APIRouter, Request, Response

from pramana_contracts import SiteModelDocument, SiteModelSummary, SiteSummary
from pramana_domain.spec_storage import spec_digest

from .. import ids
from ..accounts import site_view
from ..db import SiteModelRow
from ..errors import ApiError, not_found
from ..site_models import StoredModels
from ..tenant_routes import OrganizationRoute

router = APIRouter(prefix="/v1/orgs/{org}/sites", tags=["sites"], route_class=OrganizationRoute)


def _id(prefix: str, value: str) -> uuid.UUID:
    try:
        return ids.decode(prefix, value)
    except ValueError as exc:
        raise not_found("site model" if prefix == "model" else "site") from exc


def _store(request: Request, response: Response) -> StoredModels:
    response.headers["Cache-Control"] = "private, no-store"
    store: StoredModels = request.app.state.site_models
    return store


def _view(row: SiteModelRow) -> SiteModelSummary:
    return SiteModelSummary.model_validate(
        {
            "id": ids.encode("model", row.id),
            "org_id": ids.encode("org", row.org_id),
            "site_id": ids.encode("site", row.site_id),
            "version": row.version,
            "status": row.status,
            "spec_sha256": row.spec_sha256.hex(),
            "created_at": row.created_at,
            "published_at": row.published_at,
        }
    )


@router.get("")
async def sites(org: str, request: Request, response: Response) -> list[SiteSummary]:
    return [site_view(row) for row in await _store(request, response).sites()]


@router.get("/{site_id}")
async def site(org: str, site_id: str, request: Request, response: Response) -> SiteSummary:
    return site_view(await _store(request, response).site(_id("site", site_id)))


@router.get("/{site_id}/models")
async def models(
    org: str, site_id: str, request: Request, response: Response
) -> list[SiteModelSummary]:
    return [_view(row) for row in await _store(request, response).versions(_id("site", site_id))]


@router.get("/{site_id}/models/{model_id}")
async def model(
    org: str, site_id: str, model_id: str, request: Request, response: Response
) -> SiteModelDocument:
    store = _store(request, response)
    sid, mid = _id("site", site_id), _id("model", model_id)
    await store.site(sid)
    row = await store.row(sid, mid)
    if spec_digest(row.spec) != row.spec_sha256:
        raise ApiError(503, "MODEL_INTEGRITY_ERROR", "the saved model failed its integrity check")
    document = SiteModelDocument(
        **_view(row).model_dump(),
        spec=row.spec,
        description=(row.source or {}).get("description"),
    )
    response.headers["ETag"] = (
        '"' + hashlib.sha256(document.model_dump_json().encode()).hexdigest() + '"'
    )
    return document
