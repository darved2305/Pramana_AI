# No future annotations: FastAPI resolves dependency annotations at runtime.
"""The people who can be asked at one site, scoped to an active membership."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Path, Request, Response

from pramana_contracts import (
    ConsentPurpose,
    ConsentRecord,
    ParticipantPatch,
    ParticipantSpec,
    PersonTrackRecord,
    RecordConsent,
    SitePerson,
)

from .. import ids
from ..db import Database
from ..errors import not_found
from ..idempotency import idempotent
from ..people import SitePeople, consent_view, person_etag, person_view
from ..tenant_routes import OrganizationRoute
from ..track_record import track_records

EDITORS = ("operator", "owner", "admin")
ERASERS = ("owner", "admin")
PersonId = Annotated[str, Path(pattern=r"^[A-Za-z0-9_.:-]{1,64}$")]
router = APIRouter(
    prefix="/v1/orgs/{org}/sites/{site_id}/people",
    tags=["people"],
    route_class=OrganizationRoute,
)


def _site(value: str) -> uuid.UUID:
    try:
        return ids.decode("site", value)
    except ValueError as exc:
        raise not_found("site") from exc


def _people(request: Request, response: Response) -> SitePeople:
    response.headers["Cache-Control"] = "private, no-store"
    people: SitePeople = request.app.state.site_people
    return people


@router.get("")
async def list_people(
    org: str, site_id: str, request: Request, response: Response
) -> list[SitePerson]:
    return [person_view(r) for r in await _people(request, response).listing(_site(site_id))]


@router.get("/track-record")
async def track_record(
    org: str, site_id: str, request: Request, response: Response
) -> list[PersonTrackRecord]:
    """How often each person's answers matched causes that were later revealed or confirmed."""
    site = _site(site_id)
    await _people(request, response).listing(site)  # 404 for a site outside this workspace
    db: Database = request.app.state.db
    async with db.read() as session:
        return await track_records(session, request.state.organization.organization.id, site)


@router.post("", status_code=201)
@idempotent("org", roles=EDITORS)
async def add_person(
    org: str, site_id: str, body: ParticipantSpec, request: Request, response: Response
) -> SitePerson:
    """``409 PERSON_EXISTS`` when the id is taken at this site; roles must exist in its model."""
    row = await _people(request, response).add(_site(site_id), body)
    response.headers["ETag"] = person_etag(row)
    return person_view(row)


@router.patch(
    "/{person_id}",
    openapi_extra={
        "parameters": [
            {"name": "If-Match", "in": "header", "required": True, "schema": {"type": "string"}}
        ]
    },
)
@idempotent("org", roles=EDITORS)
async def update_person(
    org: str,
    site_id: str,
    person_id: PersonId,
    body: ParticipantPatch,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> SitePerson:
    row = await _people(request, response).update(_site(site_id), person_id, body, if_match)
    response.headers["ETag"] = person_etag(row)
    return person_view(row)


@router.post("/{person_id}/remove", status_code=204)
@idempotent("org", roles=EDITORS)
async def remove_person(
    org: str, site_id: str, person_id: PersonId, request: Request, response: Response
) -> Response:
    """Past investigations keep their own copy of who took part."""
    await _people(request, response).remove(_site(site_id), person_id)
    return Response(status_code=204)


@router.post("/{person_id}/erase", status_code=204)
@idempotent("org", roles=ERASERS)
async def erase_person(
    org: str, site_id: str, person_id: PersonId, request: Request, response: Response
) -> Response:
    """Permanently erase this person. Past investigations show "Erased person" and still replay."""
    await _people(request, response).erase(_site(site_id), person_id, request.state.principal)
    return Response(status_code=204)


@router.get("/{person_id}/consents")
async def list_consents(
    org: str, site_id: str, person_id: PersonId, request: Request, response: Response
) -> list[ConsentRecord]:
    rows = await _people(request, response).consents(_site(site_id), person_id)
    return [consent_view(r) for r in rows]


@router.post("/{person_id}/consents", status_code=201)
@idempotent("org", roles=EDITORS)
async def record_consent(
    org: str,
    site_id: str,
    person_id: PersonId,
    body: RecordConsent,
    request: Request,
    response: Response,
) -> ConsentRecord:
    row = await _people(request, response).grant_consent(
        _site(site_id), person_id, body, request.state.principal
    )
    return consent_view(row)


@router.post("/{person_id}/consents/{purpose}/withdraw", status_code=204)
@idempotent("org", roles=EDITORS)
async def withdraw_consent(
    org: str,
    site_id: str,
    person_id: PersonId,
    purpose: ConsentPurpose,
    request: Request,
    response: Response,
) -> Response:
    await _people(request, response).withdraw_consent(
        _site(site_id), person_id, purpose, request.state.principal
    )
    return Response(status_code=204)
