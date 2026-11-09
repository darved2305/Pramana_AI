# No future annotations: FastAPI resolves dependency annotations at runtime.
"""Saved-site investigations. Commands retain the existing engine and approval behavior."""

from fastapi import APIRouter, Request

from pramana_contracts import (
    CreateSiteInvestigation,
    InvestigationState,
    QuietHoursOverrideRequest,
)

from ..idempotency import idempotent
from ..investigations import InvestigationService
from ..tenant_routes import organization_router
from . import investigations, stream

OPERATOR = ("operator", "owner", "admin")
source = APIRouter()
source.routes.extend([*investigations.router.routes, *stream.router.routes])


@source.post("/v1/investigations/{inv_id}/availability/recheck", tags=["investigations"])
@idempotent("org", roles=OPERATOR)
async def recheck_availability(org: str, inv_id: str, request: Request) -> InvestigationState:
    service: InvestigationService = request.app.state.investigations
    return await service.recheck_availability(inv_id)


@source.post("/v1/investigations/{inv_id}/quiet-hours/override", tags=["investigations"])
@idempotent("org", roles=("owner", "admin"))
async def override_quiet_hours(
    org: str, inv_id: str, body: QuietHoursOverrideRequest, request: Request
) -> InvestigationState:
    service: InvestigationService = request.app.state.investigations
    return await service.override_quiet_hours(inv_id, body, request.state.principal.id)


router = organization_router(
    source,
    skip=frozenset({("POST", "/investigations")}),
    participants=frozenset(
        {
            ("GET", "/investigations/{inv_id}"),
            ("POST", "/investigations/{inv_id}/answers"),
            ("POST", "/investigations/{inv_id}/approvals/{approval_id}/capability"),
            ("POST", "/investigations/{inv_id}/interventions"),
        }
    ),
    mutations={
        ("POST", "/investigations/{inv_id}/answers"): OPERATOR,
        ("POST", "/investigations/{inv_id}/reveal"): OPERATOR,
        ("POST", "/investigations/{inv_id}/approvals"): OPERATOR,
        ("POST", "/investigations/{inv_id}/approvals/{approval_id}/decision"): ("approver",),
        ("POST", "/investigations/{inv_id}/approvals/{approval_id}/capability"): OPERATOR,
        ("POST", "/investigations/{inv_id}/interventions"): OPERATOR,
        ("POST", "/investigations/{inv_id}/participants/{participant_id}/token"): OPERATOR,
        ("POST", "/investigations/{inv_id}/availability/recheck"): OPERATOR,
        ("POST", "/investigations/{inv_id}/quiet-hours/override"): ("owner", "admin"),
    },
)


@router.post("/investigations", status_code=201, tags=["investigations"])
@idempotent("org", roles=OPERATOR)
async def create_investigation(
    org: str, body: CreateSiteInvestigation, request: Request
) -> InvestigationState:
    service: InvestigationService = request.app.state.investigations
    return await service.create(body)
