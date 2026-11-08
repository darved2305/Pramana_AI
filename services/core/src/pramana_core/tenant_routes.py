"""Organization authorization around the complete HTTP response, including stream tasks."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from fastapi import APIRouter, Request
from fastapi.routing import APIRoute
from sqlalchemy import select
from starlette.types import Receive, Scope, Send

from .auth.deps import current_principal
from .db import Database, InvestigationRow, acting_for
from .errors import ApiError, not_found
from .idempotency import IdempotencyRoute, MutationPolicy
from .org_access import participant_organization, require_organization, require_user


class OrganizationRoute(IdempotencyRoute):
    """Resolve membership before validation or replay, and retain context until response end.

    Tenant staff authority comes from membership roles. Owner/admin can manage operations;
    neither role implies approver. The account's legacy global roles never grant tenant access.
    Participant links need a signed organization claim and an explicitly allowed operation.
    WebSockets have their own boundary when those routes move here.
    """

    async def handle(self, scope: Scope, receive: Receive, send: Send) -> None:
        request = Request(scope, receive, send)
        principal = await current_principal(request)
        if principal.kind == "participant":
            if not self.endpoint.__dict__.get("pramana_participants", False):
                raise ApiError(403, "ROLE_FORBIDDEN", "this link cannot access this resource")
            access = await participant_organization(request, principal)
            actor = f"participant:{principal.token_id}"
            user_id = None
        else:
            principal = await require_user(request)
            access = await require_organization(request, principal)
            actor, user_id = f"user:{principal.id}", principal.id
        roles = set(access.roles)
        if roles.intersection({"owner", "admin"}):
            roles.add("operator")
        request.state.organization = access
        request.state.principal = replace(principal, roles=frozenset(roles))
        try:
            with acting_for(access.organization.id, user_id, actor=actor):
                inv_id = request.path_params.get("inv_id")
                if inv_id is not None:
                    db: Database = request.app.state.db
                    async with db.read() as session:
                        found = await session.scalar(
                            select(InvestigationRow).where(
                                InvestigationRow.id == str(inv_id),
                                InvestigationRow.org_id == access.organization.id,
                            )
                        )
                    if found is None:
                        raise not_found("investigation")
                    if principal.kind == "participant":
                        if (
                            found.scenario_id != principal.scenario_id
                            or principal.participant_id
                            not in {p["id"] for p in found.request["participants"]}
                        ):
                            raise not_found("investigation")
                        request.state.participant_authorized = True
                elif principal.kind == "participant":
                    raise not_found("investigation")
                await super().handle(scope, receive, send)
        finally:
            request.state.principal = principal


def organization_router(
    source: APIRouter,
    *,
    mutations: dict[tuple[str, str], tuple[str, ...]],
    skip: frozenset[tuple[str, str]] = frozenset(),
    participants: frozenset[tuple[str, str]] = frozenset(),
) -> APIRouter:
    """Reuse existing command behavior behind the new boundary during the route cutover.

    Each mutation needs an explicit role policy. WebSockets cannot silently enter this HTTP
    adapter. Legacy routes use ordinary APIRoute and are registered only outside production.
    """
    router = APIRouter(prefix="/v1/orgs/{org}", route_class=OrganizationRoute)
    for route in source.routes:
        if not isinstance(route, APIRoute):
            raise ValueError("WebSockets need a separate organization boundary")
        path = route.path.removeprefix("/v1")
        methods = route.methods or {"GET"}
        if any((method, path) in skip for method in methods):
            continue
        unsafe = methods - {"GET", "HEAD", "OPTIONS"}
        participant_methods = {method for method in methods if (method, path) in participants}
        if participant_methods and participant_methods != methods:
            raise ValueError("participant permissions must cover the entire route")
        allowed = bool(participant_methods)
        route.endpoint.__dict__["pramana_participants"] = allowed
        if unsafe:
            policies = {mutations[(method, path)] for method in unsafe}
            if len(policies) != 1:
                raise ValueError("mutations sharing an endpoint must share a role policy")
            route.endpoint.__dict__["pramana_mutation"] = MutationPolicy(
                "org", policies.pop(), participants=allowed
            )
        options: dict[str, Any] = {
            "methods": methods,
            "response_model": route.response_model,
            "status_code": route.status_code,
            "dependencies": route.dependencies,
            "tags": route.tags,
            "summary": route.summary,
            "description": route.description,
            "response_class": route.response_class,
            "responses": route.responses,
            "include_in_schema": route.include_in_schema,
        }
        router.add_api_route(path, route.endpoint, **options)
    return router
