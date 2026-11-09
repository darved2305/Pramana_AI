# No future annotations: FastAPI resolves dependency annotations at runtime.
"""The people who can be asked at one site, scoped to an active membership."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Path, Request, Response

from pramana_contracts import (
    ConsentPurpose,
    ConsentRecord,
    ConsentRequestCreated,
    ParticipantSpec,
    PersonTrackRecord,
    RecordConsent,
    SitePerson,
    SitePersonPatch,
)

from .. import ids
from ..consent import email_consent_request
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
    roles = set(request.state.principal.roles)
    include_contact = bool(roles & {"owner", "admin", "operator"})
    return [
        person_view(r, include_contact=include_contact)
        for r in await _people(request, response).listing(_site(site_id))
    ]


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
    return person_view(row, include_contact=True)


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
    body: SitePersonPatch,
    request: Request,
    response: Response,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> SitePerson:
    row = await _people(request, response).update(_site(site_id), person_id, body, if_match)
    response.headers["ETag"] = person_etag(row)
    return person_view(row, include_contact=True)


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
    if body.purpose == "contact_for_investigations":
        await request.app.state.investigations.consent_state_changed(_site(site_id), person_id)
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
    if purpose == "contact_for_investigations":
        await request.app.state.investigations.consent_state_changed(_site(site_id), person_id)
    return Response(status_code=204)


@router.post("/{person_id}/consent-requests", status_code=201)
@idempotent("org", roles=EDITORS)
async def request_consent(
    org: str, site_id: str, person_id: PersonId, request: Request, response: Response
) -> ConsentRequestCreated:
    """Create a single-use web consent link and email it when Gmail is ready."""
    response.headers["Cache-Control"] = "private, no-store"
    people = _people(request, response)
    code, expires_at, email, language, request_id = await people.request_consent_link(
        _site(site_id), person_id, request.state.principal
    )
    link_path = f"/consent/{code}"
    delivery = await email_consent_request(
        request.app.state.mailer,
        request.app.state.settings.invitation_link_base,
        email,
        link_path,
        language,
        request_id,
    )
    return ConsentRequestCreated(
        link_path=link_path, expires_at=expires_at, email_delivery=delivery
    )
