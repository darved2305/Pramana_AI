# No future annotations: FastAPI resolves dependency annotations at runtime.
"""The people who can be asked at one site, scoped to an active membership."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Path, Query, Request, Response
from sqlalchemy import select

from pramana_contracts import (
    ConsentPurpose,
    ConsentRecord,
    CursorPage,
    ParticipantPatch,
    ConsentRequestCreated,
    ParticipantSpec,
    PersonTrackRecord,
    RecordConsent,
    SitePerson,
    SitePersonPatch,
)

from .. import ids
from ..cursors import CursorCodec
from ..db import Database, InvestigationRow, ObservationRow
from ..errors import ApiError, not_found
from ..consent import email_consent_request
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
    org: str,
    site_id: str,
    request: Request,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
) -> CursorPage[SitePerson]:
    rows, next_cursor = await _people(request, response).listing_page(
        _site(site_id),
        limit=limit,
        cursor=cursor,
        q=q,
        codec=request.app.state.cursor_codec,
    )
    return CursorPage[SitePerson](
        items=[person_view(r) for r in rows], limit=limit, next_cursor=next_cursor
    )


@router.get("/track-record")
async def track_record(
    org: str,
    site_id: str,
    request: Request,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    person_id: Annotated[list[str] | None, Query()] = None,
) -> CursorPage[PersonTrackRecord]:
    """How often each person's answers matched causes that were later revealed or confirmed."""
    site = _site(site_id)
    await _people(request, response).require_site(site)
    if person_id is not None and len(person_id) > 100:
        raise ApiError(422, "TOO_MANY_PEOPLE", "request track records for at most 100 people")
    db: Database = request.app.state.db
    codec: CursorCodec = request.app.state.cursor_codec
    org_id = request.state.organization.organization.id
    person_filter = sorted(set(person_id or []))
    filters = {"person_id": person_filter}
    scope = f"track-record:{site}"
    sort = codec.decode(cursor, scope=scope, org_id=str(org_id), filters=filters, sort_fields=1)
    async with db.read() as session:
        people_query = (
            select(ObservationRow.participant_id)
            .join(
                InvestigationRow,
                (InvestigationRow.org_id == ObservationRow.org_id)
                & (InvestigationRow.id == ObservationRow.investigation_id),
            )
            .where(
                ObservationRow.org_id == org_id,
                ObservationRow.state.in_(("committed", "superseded")),
                InvestigationRow.org_id == org_id,
                InvestigationRow.site_id == site,
                InvestigationRow.ground_truth.is_not(None),
            )
        )
        if person_id is not None:
            people_query = people_query.where(ObservationRow.participant_id.in_(person_filter))
        if sort is not None:
            people_query = people_query.where(ObservationRow.participant_id > str(sort[0]))
        page_ids = list(
            await session.scalars(
                people_query.distinct().order_by(ObservationRow.participant_id).limit(limit + 1)
            )
        )
        has_more = len(page_ids) > limit
        page_ids = page_ids[:limit]
        rows = await track_records(session, org_id, site, person_ids=set(page_ids))
    next_cursor = (
        codec.encode(
            scope=scope,
            org_id=str(org_id),
            filters=filters,
            sort=[page_ids[-1]],
        )
        if has_more and page_ids
        else None
    )
    return CursorPage[PersonTrackRecord](items=rows, limit=limit, next_cursor=next_cursor)


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
    org: str,
    site_id: str,
    person_id: PersonId,
    request: Request,
    response: Response,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
    purpose: Annotated[ConsentPurpose | None, Query()] = None,
) -> CursorPage[ConsentRecord]:
    rows, next_cursor = await _people(request, response).consent_page(
        _site(site_id),
        person_id,
        limit=limit,
        cursor=cursor,
        purpose=purpose,
        codec=request.app.state.cursor_codec,
    )
    return CursorPage[ConsentRecord](
        items=[consent_view(r) for r in rows], limit=limit, next_cursor=next_cursor
    )


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
