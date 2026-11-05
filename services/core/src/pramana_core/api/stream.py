# No ``from __future__ import annotations``: FastAPI resolves dependency annotations at runtime.
"""Event push channel and replay check (``/v1/investigations/{id}/stream``, ``.../replay``)."""

from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Request
from pydantic import BaseModel

from ..auth.deps import require_staff
from ..errors import ApiError
from ..investigations import InvestigationService
from ..runtime.broadcast import EventBroadcaster, TooManySubscribersError
from ..runtime.stream import EventStreamResponse, event_stream, parse_last_event_id

router = APIRouter(prefix="/v1/investigations", tags=["investigations"])


class ReplayResult(BaseModel):
    investigation_id: str
    status: str
    events_replayed: int
    identical: bool
    """The belief rebuilt from the event log equals the last recorded ``BeliefUpdated``,
    compared as canonical JSON byte for byte."""
    replayed_sha256: str
    recorded_sha256: str | None
    final_belief: dict[str, Any]
    """Rebuilt from the event log alone."""
    recorded_belief: dict[str, Any] | None
    """The last ``BeliefUpdated`` payload."""
    recorded_model_version: str
    """Probability model that wrote the log (``InvestigationCreated``)."""
    current_model_version: str
    engine_changed: bool
    """True when the two differ: a mismatch is then an engine upgrade, not corruption."""


@router.get(
    "/{inv_id}/stream",
    response_class=EventStreamResponse,
    status_code=200,
    responses={
        200: {
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
            "description": (
                "Server-Sent Events. Each log event has `id: <seq>` and `data: <EventEnvelope>`. "
                "Control events: `ready`, `reset`, `bye`. Comments `: ping` are heartbeats."
            ),
        }
    },
)
async def stream_events(
    inv_id: str,
    request: Request,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    last_event_id: Annotated[str | None, Header()] = None,
) -> EventStreamResponse:
    """Push the investigation's events: backfill after ``after_seq`` (or the browser's
    ``Last-Event-ID``, whichever is later), then follow new events live."""
    await require_staff()(request)  # the log holds everyone's answers: staff only
    svc: InvestigationService = request.app.state.investigations
    broadcaster: EventBroadcaster = request.app.state.broadcaster
    cfg = request.app.state.settings
    await svc.head_seq(inv_id)  # 404 before the stream starts
    resumed = parse_last_event_id(last_event_id)
    start = max(after_seq, resumed or 0)
    try:
        sub = broadcaster.subscribe(inv_id)
    except TooManySubscribersError as exc:
        raise ApiError(429, "TOO_MANY_SUBSCRIBERS", "too many open event streams") from exc

    async def fetch(after: int, limit: int) -> Any:
        return await svc.events(inv_id, after, limit)

    async def head() -> int:
        return await svc.head_seq(inv_id)

    body = event_stream(
        sub,
        start,
        fetch,
        head,
        heartbeat_s=cfg.event_stream_heartbeat_s,
        max_duration_s=cfg.event_stream_max_s,
    )
    return EventStreamResponse(body, stall_s=cfg.event_stream_stall_s, on_close=sub.close)


@router.get("/{inv_id}/replay")
async def replay_check(inv_id: str, request: Request) -> ReplayResult:
    """Rebuild the investigation from its event log and compare with the recorded belief."""
    await require_staff()(request)
    svc: InvestigationService = request.app.state.investigations
    check = await svc.replay(inv_id)
    return ReplayResult(
        investigation_id=check.investigation_id,
        status=check.status,
        events_replayed=check.events_replayed,
        identical=check.identical,
        replayed_sha256=check.replayed_sha256,
        recorded_sha256=check.recorded_sha256,
        final_belief=check.replayed,
        recorded_belief=check.recorded,
        recorded_model_version=check.recorded_model_version,
        current_model_version=check.current_model_version,
        engine_changed=check.engine_changed,
    )
