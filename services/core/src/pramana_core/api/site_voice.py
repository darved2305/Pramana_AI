# No future annotations: FastAPI resolves dependency annotations at runtime.
"""Voice inside a workspace: question audio, spoken answers, and the live media sockets.

HTTP routes reuse the voice-turn handlers behind the organization boundary (participant links
need their signed organization claim, and only for their own investigation). WebSockets cannot
pass through that HTTP boundary, so they take the organization id in the path, run inside that
organization's row-level security context, and require the token's organization claim to match.
"""

from fastapi import APIRouter, Request, WebSocket
from fastapi.routing import APIRoute
from sqlalchemy import select

from .. import ids
from ..db import Database, OrganizationRow, acting_for
from ..org_access import require_user
from ..tenant_routes import organization_router
from ..voice.call import ParticipantCall
from ..voice.media import MediaSession
from . import voice_turns

OPERATOR = ("operator", "owner", "admin")
_http = APIRouter()
_http.routes.extend(r for r in voice_turns.router.routes if isinstance(r, APIRoute))
router = organization_router(
    _http,
    participants=frozenset(
        {
            ("GET", "/investigations/{inv_id}/questions/{question_id}/audio"),
            ("POST", "/investigations/{inv_id}/answers/voice"),
        }
    ),
    mutations={("POST", "/investigations/{inv_id}/answers/voice"): OPERATOR},
)
sockets = APIRouter(prefix="/v1/orgs/{org}/investigations", tags=["voice turns"])


def _organization(org: str) -> str | None:
    """Sockets take the organization id (``org_...``), which the participant token carries."""
    try:
        ids.decode("org", org)
    except ValueError:
        return None
    return org


async def _active_organization(db: Database, organization: str) -> bool:
    org_id = ids.decode("org", organization)
    with acting_for(org_id, actor="participant:socket"):
        async with db.read() as session:
            row = await session.scalar(select(OrganizationRow).where(OrganizationRow.id == org_id))
    return row is not None and row.deleted_at is None


@sockets.websocket("/{inv_id}/questions/{question_id}/media")
async def question_media(ws: WebSocket, org: str, inv_id: str, question_id: str) -> None:
    organization = _organization(org)
    if organization is None:
        await ws.close(code=4404)
        return
    state = ws.app.state
    if not await _active_organization(state.db, organization):
        await ws.close(code=4404)
        return
    with acting_for(ids.decode("org", organization), None, actor="participant:socket"):
        await MediaSession(
            ws,
            inv_id,
            question_id,
            state.investigations,
            state.gnani,
            state.question_audio,
            state.broadcaster,
            state.media_sessions,
            state.settings.voice_max_stream_s,
            organization=organization,
        ).run()


@sockets.websocket("/{inv_id}/participants/{participant_id}/call")
async def participant_call(ws: WebSocket, org: str, inv_id: str, participant_id: str) -> None:
    organization = _organization(org)
    if organization is None:
        await ws.close(code=4404)
        return
    state = ws.app.state
    if not await _active_organization(state.db, organization):
        await ws.close(code=4404)
        return
    with acting_for(ids.decode("org", organization), None, actor="participant:socket"):
        await ParticipantCall(
            ws,
            inv_id,
            participant_id,
            state.investigations,
            state.gnani,
            state.question_audio,
            state.broadcaster,
            state.media_sessions,
            state.settings.voice_max_stream_s,
            organization=organization,
        ).run()


account = APIRouter(prefix="/v1/voice", tags=["voice"])


@account.get("/status")
async def voice_status(request: Request) -> dict[str, object]:
    """Whether voice works here, for anyone signed in (production; no provider URL or spend)."""
    await require_user(request)
    g = request.app.state.gnani
    return {
        "configured": g.configured,
        "provider": g.provider,
        "provider_host": None,
        "stt_model": "prisma-v3.0",
        "tts_models": ["timbre-v3.0", "timbre-v2.5"],
    }
