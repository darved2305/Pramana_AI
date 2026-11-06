# No ``from __future__ import annotations``: FastAPI resolves dependency annotations at runtime.
"""Investigation routes (``/v1/investigations``)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from pramana_contracts import (
    AnswerResult,
    ApprovalDecision,
    CapabilityGrant,
    ChallengeAnswerResult,
    CreateInvestigation,
    EventEnvelope,
    InvestigationPage,
    InvestigationPreset,
    InvestigationState,
    InvestigationStatus,
    ReportIntervention,
    RequestApproval,
    StaffRole,
    SubmitAnswer,
)

from ..auth.deps import authorize_participant, authorize_read, require_staff
from ..auth.service import Principal
from ..directory import ConsoleQueries
from ..investigations import InvestigationService
from ..presets import investigation_presets
from ..visibility import visible_answer, visible_state

router = APIRouter(prefix="/v1/investigations", tags=["investigations"])


def service(request: Request) -> InvestigationService:
    svc: InvestigationService = request.app.state.investigations
    return svc


Svc = Annotated[InvestigationService, Depends(service)]
Operator = Depends(require_staff(StaffRole.OPERATOR))
Approver = Annotated[Principal, Depends(require_staff(StaffRole.APPROVER))]


@router.get("", dependencies=[Depends(require_staff())])
async def list_investigations(
    request: Request,
    status: Annotated[list[InvestigationStatus] | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InvestigationPage:
    """Newest first. ``status`` may repeat; ``q`` searches the report text and the id."""
    queries: ConsoleQueries = request.app.state.console
    return await queries.list_investigations(statuses=status or [], q=q, limit=limit, offset=offset)


@router.post("", status_code=201, dependencies=[Operator])
async def create_investigation(body: CreateInvestigation, svc: Svc) -> InvestigationState:
    return await svc.create(body)


@router.get("/presets", dependencies=[Depends(require_staff())])
async def list_investigation_presets() -> list[InvestigationPreset]:
    """Requests the S2 and S7 scenarios use to create a reproducible investigation."""
    return investigation_presets()


@router.get("/{inv_id}")
async def get_investigation(inv_id: str, svc: Svc, request: Request) -> InvestigationState:
    who = await authorize_read(request, inv_id)
    return visible_state(await svc.get(inv_id), who)


@router.post("/{inv_id}/answers")
async def submit_answer(
    inv_id: str, body: SubmitAnswer, svc: Svc, request: Request
) -> AnswerResult | ChallengeAnswerResult:
    who = await authorize_participant(request, inv_id, body.participant_id)
    return visible_answer(await svc.answer(inv_id, body), who)


@router.post("/{inv_id}/reveal", dependencies=[Operator])
async def reveal_ground_truth(inv_id: str, svc: Svc) -> InvestigationState:
    return await svc.reveal(inv_id)


@router.get("/{inv_id}/events")
async def list_events(
    inv_id: str,
    svc: Svc,
    request: Request,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[EventEnvelope]:
    # The log holds everyone's answers and the engine's reasoning: staff only.
    await require_staff()(request)
    return await svc.events(inv_id, after_seq, limit)


@router.post("/{inv_id}/approvals", status_code=201, dependencies=[Operator])
async def request_approval(inv_id: str, body: RequestApproval, svc: Svc) -> InvestigationState:
    """Ask a human approver for a consequential action the decision calls for."""
    return await svc.request_approval(inv_id, body)


@router.post("/{inv_id}/approvals/{approval_id}/decision")
async def decide_approval(
    inv_id: str, approval_id: str, body: ApprovalDecision, svc: Svc, who: Approver
) -> InvestigationState:
    """Needs the approver role. The approval records the signed-in approver; a free-text
    ``approver_id`` is used only when sign-in is not enforced (tests)."""
    approver = (body.approver_id or who.id) if who.kind == "open" else who.id
    return await svc.decide_approval(inv_id, approval_id, body, approver_id=approver)


@router.post("/{inv_id}/approvals/{approval_id}/capability")
async def issue_capability(
    inv_id: str, approval_id: str, participant_id: str, svc: Svc, request: Request
) -> CapabilityGrant:
    """The approved executor collects the single-use capability (expires in 5 minutes)."""
    await authorize_participant(request, inv_id, participant_id)
    return await svc.capability_for(inv_id, approval_id, participant_id)


@router.post("/{inv_id}/interventions")
async def report_intervention(
    inv_id: str, body: ReportIntervention, svc: Svc, request: Request
) -> InvestigationState:
    """The executor reports the action as done; verification questions follow."""
    who = await authorize_participant(request, inv_id, body.participant_id)
    return visible_state(await svc.report_intervention(inv_id, body), who)


@router.post("/{inv_id}/participants/{participant_id}/token", dependencies=[Operator])
async def participant_token(inv_id: str, participant_id: str, svc: Svc) -> dict[str, str]:
    """Mint the participant's join token (operator only). It works at the simulator and, for
    that participant's own answers and actions, at the core."""
    out = await svc.participant_token(inv_id, participant_id)
    return out
