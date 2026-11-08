# No future annotations: FastAPI resolves dependency annotations at runtime.
"""Account routing and workspace setup. Mutations require idempotency keys."""

from fastapi import APIRouter, Request, Response

from pramana_contracts.accounts import (
    CreateOrganization,
    CurrentAccount,
    OnboardingPatch,
    OnboardingState,
    OrganizationCreated,
    OrganizationSummary,
)

from ..accounts import AccountService, organization_view
from ..idempotency import IdempotencyRoute, idempotent
from ..org_access import require_organization, require_user

router = APIRouter(prefix="/v1", tags=["accounts"], route_class=IdempotencyRoute)


@router.get("/me")
async def me(request: Request, response: Response) -> CurrentAccount:
    principal = await require_user(request)
    service: AccountService = request.app.state.accounts
    response.headers["Cache-Control"] = "no-store"
    return await service.me(principal)


@router.get("/onboarding")
async def onboarding(request: Request, response: Response) -> OnboardingState:
    principal = await require_user(request)
    service: AccountService = request.app.state.accounts
    state = (await service.me(principal)).onboarding
    response.headers["ETag"] = f'"{state.version}"'
    response.headers["Cache-Control"] = "no-store"
    return state


@router.patch(
    "/onboarding",
    openapi_extra={
        "parameters": [
            {"name": "If-Match", "in": "header", "required": True, "schema": {"type": "string"}}
        ],
        "responses": {
            "428": {"description": "The form version is required"},
            "412": {"description": "The form changed in another tab"},
        },
    },
)
@idempotent("user")
async def save_onboarding(
    body: OnboardingPatch, request: Request, response: Response
) -> OnboardingState:
    principal = await require_user(request)
    service: AccountService = request.app.state.accounts
    state = await service.patch_onboarding(principal, body, request.headers.get("if-match"))
    response.headers["ETag"] = f'"{state.version}"'
    response.headers["Cache-Control"] = "no-store"
    return state


@router.post("/orgs", status_code=201)
@idempotent("user", verified=True)
async def create_organization(
    body: CreateOrganization, request: Request, response: Response
) -> OrganizationCreated:
    principal = await require_user(request, verified=True)
    service: AccountService = request.app.state.accounts
    response.headers["Cache-Control"] = "no-store"
    return await service.create_organization(principal, body)


@router.get("/orgs/{org}")
async def organization(org: str, request: Request, response: Response) -> OrganizationSummary:
    principal = await require_user(request)
    access = await require_organization(request, principal)
    response.headers["Cache-Control"] = "no-store"
    return organization_view(access.organization, access.roles)
