# No ``from __future__ import annotations``: FastAPI resolves dependency annotations at runtime.
"""Investigation routes (``/v1/investigations``)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from pramana_contracts import (
    AnswerResult,
    ApprovalDecision,
    CapabilityGrant,
    CreateInvestigation,
    EventEnvelope,
    InvestigationState,
    ReportIntervention,
    RequestApproval,
    SubmitAnswer,
)

from ..investigations import InvestigationService

router = APIRouter(prefix="/v1/investigations", tags=["investigations"])


def service(request: Request) -> InvestigationService:
    svc: InvestigationService = request.app.state.investigations
    return svc


Svc = Annotated[InvestigationService, Depends(service)]


@router.post("", status_code=201)
async def create_investigation(body: CreateInvestigation, svc: Svc) -> InvestigationState:
    return await svc.create(body)


@router.get("/{inv_id}")
async def get_investigation(inv_id: str, svc: Svc) -> InvestigationState:
    return await svc.get(inv_id)


@router.post("/{inv_id}/answers")
async def submit_answer(inv_id: str, body: SubmitAnswer, svc: Svc) -> AnswerResult:
    return await svc.answer(inv_id, body)


@router.post("/{inv_id}/reveal")
async def reveal_ground_truth(inv_id: str, svc: Svc) -> InvestigationState:
    return await svc.reveal(inv_id)


@router.get("/{inv_id}/events")
async def list_events(
    inv_id: str,
    svc: Svc,
    after_seq: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[EventEnvelope]:
    return await svc.events(inv_id, after_seq, limit)


@router.post("/{inv_id}/approvals", status_code=201)
async def request_approval(inv_id: str, body: RequestApproval, svc: Svc) -> InvestigationState:
    """Ask a human approver for a consequential action the decision calls for."""
    return await svc.request_approval(inv_id, body)


@router.post("/{inv_id}/approvals/{approval_id}/decision")
async def decide_approval(
    inv_id: str, approval_id: str, body: ApprovalDecision, svc: Svc
) -> InvestigationState:
    return await svc.decide_approval(inv_id, approval_id, body)


@router.post("/{inv_id}/approvals/{approval_id}/capability")
async def issue_capability(
    inv_id: str, approval_id: str, participant_id: str, svc: Svc
) -> CapabilityGrant:
    """The approved executor collects the single-use capability (expires in 5 minutes)."""
    return await svc.capability_for(inv_id, approval_id, participant_id)


@router.post("/{inv_id}/interventions")
async def report_intervention(
    inv_id: str, body: ReportIntervention, svc: Svc
) -> InvestigationState:
    """The executor reports the action as done; verification questions follow."""
    return await svc.report_intervention(inv_id, body)


@router.post("/{inv_id}/participants/{participant_id}/token")
async def participant_token(inv_id: str, participant_id: str, svc: Svc) -> dict[str, str]:
    """Mint the participant's simulator token (development console; no auth in this slice)."""
    out = await svc.participant_token(inv_id, participant_id)
    return out
