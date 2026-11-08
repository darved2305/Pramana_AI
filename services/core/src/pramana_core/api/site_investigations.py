# No future annotations: FastAPI resolves dependency annotations at runtime.
"""Saved-site investigations. Commands retain the existing engine and approval behavior."""

from fastapi import APIRouter, Request

from pramana_contracts import CreateSiteInvestigation, InvestigationState

from ..idempotency import idempotent
from ..investigations import InvestigationService
from ..tenant_routes import organization_router
from . import investigations, stream

OPERATOR = ("operator", "owner", "admin")
source = APIRouter()
source.routes.extend([*investigations.router.routes, *stream.router.routes])
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
    },
)


@router.post("/investigations", status_code=201, tags=["investigations"])
@idempotent("org", roles=OPERATOR)
async def create_investigation(
    org: str, body: CreateSiteInvestigation, request: Request
) -> InvestigationState:
    service: InvestigationService = request.app.state.investigations
    return await service.create(body)
