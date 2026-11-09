# No future annotations: FastAPI resolves dependency annotations at runtime.
"""Public one-time consent links. The secret, not a user session, authorizes the response."""

from fastapi import APIRouter, Request, Response

from pramana_contracts import ConsentLinkView, ConsentResponseView, SubmitConsentResponse

from ..db import Database, acting_for
from ..people import SitePeople

router = APIRouter(prefix="/v1/consent-links", tags=["consent"])


@router.get("/{code}")
async def get_consent_link(code: str, request: Request, response: Response) -> ConsentLinkView:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    people: SitePeople = request.app.state.site_people
    return await people.consent_link(code)


@router.post("/{code}")
async def respond_to_consent_link(
    code: str, body: SubmitConsentResponse, request: Request, response: Response
) -> ConsentResponseView:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    people: SitePeople = request.app.state.site_people
    db: Database = request.app.state.db
    async with db.unit_of_work():
        result = await people.respond_to_consent_link(code, body)
        with acting_for(result.org_id, actor=f"consent-link:{result.person_id}"):
            await request.app.state.investigations.consent_state_changed(
                result.site_id, result.person_id
            )
    return result.view
