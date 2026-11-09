"""User routing, survey autosave and atomic workspace provisioning."""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pramana_contracts import AuthSession, StaffRole
from pramana_contracts.accounts import (
    AccountPreferences,
    CreateOrganization,
    CurrentAccount,
    HomeLayout,
    IdentitySummary,
    JoinSuggestion,
    OnboardingAnswers,
    OnboardingPatch,
    OnboardingState,
    OnboardingStep,
    OrganizationCreated,
    OrganizationKind,
    OrganizationRole,
    OrganizationSummary,
    PendingInvitation,
    PreferencesPatch,
    SiteSummary,
)

from . import ids
from .account_rows import (
    InvitationRow,
    JoinRequestRow,
    ModelTemplateRow,
    OnboardingRow,
    OrganizationDomainRow,
    PreferenceRow,
)
from .auth.service import Principal
from .db import (
    AuditLogRow,
    Database,
    MembershipRow,
    OrganizationRow,
    SiteModelRow,
    SiteRow,
    UserIdentityRow,
    acting_for,
)
from .errors import ApiError, not_found

RESERVED_SLUGS = frozenset(
    {
        "api",
        "auth",
        "login",
        "app",
        "onboarding",
        "account",
        "settings",
        "new",
        "invite",
        "admin",
        "billing",
        "investigations",
        "participants",
        "people",
        "sites",
        "evaluation",
        "voice",
        "preview",
        "join",
        "home",
    }
)


def onboarding_view(row: OnboardingRow) -> OnboardingState:
    return OnboardingState(
        step=OnboardingStep(row.step),
        answers=OnboardingAnswers.model_validate(row.answers),
        version=row.version,
        org_id=ids.encode("org", row.org_id) if row.org_id else None,
        dismissed_at=row.dismissed_at,
        completed_at=row.completed_at,
        updated_at=row.updated_at,
    )


def organization_view(
    row: OrganizationRow, roles: list[str] | tuple[str, ...]
) -> OrganizationSummary:
    return OrganizationSummary(
        id=ids.encode("org", row.id),
        slug=row.slug,
        name=row.name,
        kind=OrganizationKind(row.kind),
        roles=[OrganizationRole(role) for role in sorted(roles)],
        timezone=row.timezone,
        version=row.version,
        created_at=row.created_at,
        deleted_at=row.deleted_at,
        purge_after=row.purge_after,
    )


def site_view(row: SiteRow) -> SiteSummary:
    return SiteSummary.model_validate(
        {
            "id": ids.encode("site", row.id),
            "org_id": ids.encode("org", row.org_id),
            "name": row.name,
            "kind": row.kind,
            "mode": row.mode,
            "current_model_id": ids.encode("model", row.current_model_id)
            if row.current_model_id
            else None,
            "created_at": row.created_at,
        }
    )


def destination(
    state: OnboardingState,
    organizations: list[OrganizationSummary],
    preferred: str | None,
) -> str:
    if (
        state.dismissed_at is None
        and state.completed_at is None
        and state.step
        not in {
            OnboardingStep.WELCOME,
            OnboardingStep.DONE,
        }
    ):
        return f"/onboarding/{state.step.value}"
    active = [org for org in organizations if org.deleted_at is None]
    if active:
        chosen = next((org for org in active if org.id == preferred), active[0])
        return f"/app/{chosen.slug}"
    return "/onboarding/welcome"


def _slug(name: str) -> str:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:32].rstrip("-")
    return value if len(value) >= 3 and value not in RESERVED_SLUGS else "workspace"


def version_match(value: str | None, current: int) -> None:
    if value is None:
        raise ApiError(
            428, "PRECONDITION_REQUIRED", "send the version shown when you opened this form"
        )
    if value != f'"{current}"':
        raise ApiError(
            412,
            "STATE_CONFLICT",
            "this form changed in another tab; review the latest version",
            details={"current_version": current},
        )


class AccountService:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    async def _ensure(session: AsyncSession, user_id: str) -> tuple[OnboardingRow, PreferenceRow]:
        await session.execute(
            insert(OnboardingRow)
            .values(user_id=user_id, answers={"version": 1})
            .on_conflict_do_nothing()
        )
        await session.execute(
            insert(PreferenceRow)
            .values(user_id=user_id, last_site_by_org={}, home_layout={})
            .on_conflict_do_nothing()
        )
        state = (
            await session.execute(
                select(OnboardingRow).where(OnboardingRow.user_id == user_id).with_for_update()
            )
        ).scalar_one()
        preferences = (
            await session.execute(select(PreferenceRow).where(PreferenceRow.user_id == user_id))
        ).scalar_one()
        return state, preferences

    async def me(self, principal: Principal) -> CurrentAccount:
        hosted_domain = (
            principal.hosted_domain.lower()
            if principal.email_verified
            and principal.auth_method == "google"
            and principal.hosted_domain
            and principal.hosted_domain.lower() == principal.email.rsplit("@", 1)[-1].lower()
            else None
        )
        with acting_for(None, principal.id, hosted_domain=hosted_domain):
            async with self.db.transaction() as session:
                state, preferences = await self._ensure(session, principal.id)
                memberships = list(
                    (
                        await session.execute(
                            select(OrganizationRow, MembershipRow.roles)
                            .join(MembershipRow, MembershipRow.org_id == OrganizationRow.id)
                            .where(
                                MembershipRow.user_id == principal.id,
                                MembershipRow.status == "active",
                            )
                            .order_by(OrganizationRow.created_at, OrganizationRow.id)
                        )
                    ).all()
                )
                active_ids = {org.id for org, _ in memberships if org.deleted_at is None}
                if state.org_id is not None and state.org_id not in active_ids:
                    state.org_id = None
                    if state.completed_at is None:
                        state.step = "welcome"
                    state.version += 1
                    state.updated_at = datetime.now(UTC)
                if (
                    preferences.last_org_id is not None
                    and preferences.last_org_id not in active_ids
                ):
                    preferences.last_org_id = None
                    preferences.updated_at = datetime.now(UTC)
                identities = list(
                    await session.scalars(
                        select(UserIdentityRow)
                        .where(UserIdentityRow.user_id == principal.id)
                        .order_by(UserIdentityRow.created_at)
                    )
                )
                invited = (
                    (
                        await session.execute(
                            select(InvitationRow, OrganizationRow.name)
                            .join(OrganizationRow, OrganizationRow.id == InvitationRow.org_id)
                            .where(
                                InvitationRow.email == principal.email.lower(),
                                InvitationRow.accepted_at.is_(None),
                                InvitationRow.revoked_at.is_(None),
                                InvitationRow.expires_at > datetime.now(UTC),
                                OrganizationRow.deleted_at.is_(None),
                            )
                            .order_by(InvitationRow.created_at.desc())
                            .limit(20)
                        )
                    ).all()
                    if principal.email_verified
                    else []
                )
                suggestions: list[JoinSuggestion] = []
                if hosted_domain is not None:
                    matching = (
                        await session.execute(
                            select(OrganizationDomainRow, OrganizationRow)
                            .join(
                                OrganizationRow,
                                OrganizationRow.id == OrganizationDomainRow.org_id,
                            )
                            .where(
                                OrganizationDomainRow.domain == hosted_domain,
                                OrganizationDomainRow.verified_at.is_not(None),
                                OrganizationDomainRow.join_policy.in_(("request", "auto")),
                                OrganizationRow.deleted_at.is_(None),
                            )
                            .order_by(OrganizationRow.name, OrganizationRow.id)
                        )
                    ).all()
                    pending = {
                        request.org_id: request.id
                        for request in await session.scalars(
                            select(JoinRequestRow).where(
                                JoinRequestRow.requester_id == principal.id,
                                JoinRequestRow.status == "pending",
                            )
                        )
                    }
                    suggestions = [
                        JoinSuggestion(
                            organization_id=ids.encode("org", org.id),
                            organization_name=org.name,
                            domain=domain.domain,
                            policy=domain.join_policy,
                            request_id=ids.encode("join", pending[org.id])
                            if org.id in pending
                            else None,
                            request_status="pending" if org.id in pending else None,
                        )
                        for domain, org in matching
                        if org.id not in active_ids
                    ]
                await session.flush()
                orgs = [organization_view(org, roles) for org, roles in memberships]
                onboard = onboarding_view(state)
                preferred = (
                    ids.encode("org", preferences.last_org_id) if preferences.last_org_id else None
                )
                return CurrentAccount(
                    user=AuthSession(
                        user_id=principal.id,
                        display_name=principal.display_name,
                        email=principal.email,
                        roles=[StaffRole(r) for r in sorted(principal.roles)],
                        expires_at=principal.expires_at or datetime.now(UTC),
                        email_verified=principal.email_verified,
                    ),
                    identities=[
                        IdentitySummary(
                            id=ids.encode("ident", identity.id),
                            provider=identity.provider,
                            email_at_link=identity.email_at_link,
                            hosted_domain=identity.hosted_domain,
                            last_used_at=identity.last_used_at,
                        )
                        for identity in identities
                    ],
                    memberships=orgs,
                    pending_invitations=[
                        PendingInvitation(
                            id=ids.encode("invite", row.id),
                            organization_id=ids.encode("org", row.org_id),
                            organization_name=name,
                            roles=[OrganizationRole(role) for role in sorted(row.roles)],
                            expires_at=row.expires_at,
                        )
                        for row, name in invited
                        if row.org_id not in active_ids
                    ],
                    join_suggestions=suggestions,
                    onboarding=onboard,
                    destination=destination(onboard, orgs, preferred),
                    preferences=AccountPreferences(
                        last_org_id=preferred,
                        last_site_by_org=preferences.last_site_by_org,
                        home_layout=HomeLayout.model_validate(preferences.home_layout),
                    ),
                )

    async def save_preferences(
        self, principal: Principal, patch: PreferencesPatch
    ) -> AccountPreferences:
        with acting_for(None, principal.id):
            async with self.db.transaction() as session:
                _, preferences = await self._ensure(session, principal.id)
                active = {
                    org_id
                    for (org_id,) in (
                        await session.execute(
                            select(MembershipRow.org_id).where(
                                MembershipRow.user_id == principal.id,
                                MembershipRow.status == "active",
                            )
                        )
                    ).all()
                }

                def own(value: str) -> uuid.UUID:
                    try:
                        org_id = ids.decode("org", value)
                    except ValueError as exc:
                        raise not_found("organization") from exc
                    if org_id not in active:
                        raise not_found("organization")
                    return org_id

                fields = patch.model_fields_set
                if "last_org_id" in fields:
                    preferences.last_org_id = (
                        own(patch.last_org_id) if patch.last_org_id is not None else None
                    )
                if patch.last_site is not None:
                    org_id = own(patch.last_site.org_id)
                    try:
                        ids.decode("site", patch.last_site.site_id)
                    except ValueError as exc:
                        raise not_found("site") from exc
                    preferences.last_site_by_org = {
                        **preferences.last_site_by_org,
                        ids.encode("org", org_id): patch.last_site.site_id,
                    }
                if patch.home_layout is not None:
                    preferences.home_layout = patch.home_layout.model_dump(mode="json")
                preferences.updated_at = datetime.now(UTC)
                await session.flush()
                return AccountPreferences(
                    last_org_id=ids.encode("org", preferences.last_org_id)
                    if preferences.last_org_id
                    else None,
                    last_site_by_org=preferences.last_site_by_org,
                    home_layout=HomeLayout.model_validate(preferences.home_layout),
                )

    async def patch_onboarding(
        self,
        principal: Principal,
        patch: OnboardingPatch,
        etag: str | None,
    ) -> OnboardingState:
        with acting_for(None, principal.id):
            async with self.db.transaction() as session:
                state, _ = await self._ensure(session, principal.id)
                version_match(etag, state.version)
                if state.org_id is not None and not await session.scalar(
                    select(MembershipRow.user_id).where(
                        MembershipRow.org_id == state.org_id,
                        MembershipRow.user_id == principal.id,
                        MembershipRow.status == "active",
                    )
                ):
                    raise ApiError(
                        409,
                        "MEMBERSHIP_CHANGED",
                        "reload this form after your workspace access changed",
                    )
                if patch.answers is not None:
                    answers = OnboardingAnswers.model_validate(
                        {
                            **state.answers,
                            **patch.answers.model_dump(mode="json", exclude_unset=True),
                        }
                    )
                    state.answers = answers.model_dump(mode="json")
                if patch.step is not None:
                    if state.org_id is None and patch.step in {
                        OnboardingStep.SANDBOX,
                        OnboardingStep.SITE,
                        OnboardingStep.PEOPLE,
                        OnboardingStep.TEST_CALL,
                        OnboardingStep.DONE,
                    }:
                        raise ApiError(
                            409, "WORKSPACE_REQUIRED", "create your workspace before this step"
                        )
                    state.step = patch.step.value
                    if patch.step == OnboardingStep.DONE:
                        state.completed_at = datetime.now(UTC)
                if patch.dismissed is not None:
                    state.dismissed_at = datetime.now(UTC) if patch.dismissed else None
                state.version += 1
                state.updated_at = datetime.now(UTC)
                await session.flush()
                return onboarding_view(state)

    async def create_organization(
        self,
        principal: Principal,
        request: CreateOrganization,
    ) -> OrganizationCreated:
        if not principal.email_verified:
            raise ApiError(403, "EMAIL_VERIFICATION_REQUIRED", "verify your email first")
        # Database.unit_of_work() joins this transaction and the returned HTTP response.
        with acting_for(None, principal.id):
            async with self.db.transaction() as session:
                state, preferences = await self._ensure(session, principal.id)
                answers = OnboardingAnswers.model_validate(state.answers)
                first_name = (
                    principal.display_name.split()[0] if principal.display_name.split() else ""
                )
                default_name = f"{first_name}'s workspace" if first_name else "My workspace"
                name = (request.name or default_name).strip()
                if not name:
                    raise ApiError(422, "ORGANIZATION_NAME_REQUIRED", "choose a workspace name")
                org_id = ids.uuid7()
                slug = request.slug or f"{_slug(name)}-{org_id.hex[-6:]}"
                if slug in RESERVED_SLUGS:
                    raise ApiError(
                        409,
                        "SLUG_TAKEN",
                        "choose another workspace address",
                        details={"suggestions": [f"{slug}-team", f"{slug}-{org_id.hex[-6:]}"]},
                    )
                kind = request.kind or answers.organization_kind or OrganizationKind.OTHER
                with acting_for(org_id, principal.id):
                    # Copy context into the joined transaction before inserting the new org.
                    async with self.db.transaction() as tenant:
                        org = OrganizationRow(
                            id=org_id,
                            slug=slug,
                            name=name,
                            kind=kind.value,
                            created_by=principal.id,
                        )
                        tenant.add(org)
                        try:
                            await tenant.flush()
                        except IntegrityError as exc:
                            if getattr(exc.orig, "sqlstate", None) == "23505":
                                raise ApiError(
                                    409,
                                    "SLUG_TAKEN",
                                    "that workspace address is already taken",
                                    details={
                                        "suggestions": [
                                            f"{_slug(slug)}-{org_id.hex[-6:]}",
                                            f"{_slug(slug)}-team",
                                        ]
                                    },
                                ) from exc
                            raise
                        roles = ["owner", "operator"]
                        tenant.add(MembershipRow(org_id=org_id, user_id=principal.id, roles=roles))
                        await tenant.flush()
                        template = (
                            await tenant.execute(
                                select(ModelTemplateRow)
                                .where(ModelTemplateRow.purpose == "sandbox")
                                .order_by(ModelTemplateRow.version.desc())
                                .limit(1)
                            )
                        ).scalar_one()
                        sandbox = SiteRow(
                            id=ids.uuid7(),
                            org_id=org_id,
                            name="Sample hostel (simulated)",
                            kind=template.kind,
                            mode="sandbox",
                        )
                        live = SiteRow(
                            id=ids.uuid7(),
                            org_id=org_id,
                            name="Your first building",
                            kind=kind.value,
                            mode="live",
                        )
                        tenant.add_all([sandbox, live])
                        await tenant.flush()
                        model = SiteModelRow(
                            id=ids.uuid7(),
                            org_id=org_id,
                            site_id=sandbox.id,
                            version=1,
                            status="published",
                            spec=template.spec,
                            spec_sha256=template.spec_sha256,
                            created_by=principal.id,
                            published_at=datetime.now(UTC),
                        )
                        tenant.add(model)
                        await tenant.flush()
                        sandbox.current_model_id = model.id
                        preferences.last_org_id = org_id
                        preferences.last_site_by_org = {
                            **preferences.last_site_by_org,
                            ids.encode("org", org_id): ids.encode("site", sandbox.id),
                        }
                        preferences.updated_at = datetime.now(UTC)
                        state.org_id = org_id
                        state.step = "sandbox"
                        state.completed_at = None
                        state.dismissed_at = None
                        state.version += 1
                        state.updated_at = datetime.now(UTC)
                        tenant.add(
                            AuditLogRow(
                                id=ids.uuid7(),
                                org_id=org_id,
                                actor_kind="user",
                                actor_id=principal.id,
                                action="organization.created",
                                target_kind="organization",
                                target_id=ids.encode("org", org_id),
                                details={},
                            )
                        )
                        await tenant.flush()
                        return OrganizationCreated(
                            organization=organization_view(org, roles),
                            sandbox_site=site_view(sandbox),
                            live_site=site_view(live),
                            onboarding=onboarding_view(state),
                            destination="/onboarding/sandbox",
                        )
