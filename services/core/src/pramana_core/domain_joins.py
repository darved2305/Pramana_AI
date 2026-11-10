"""Verified workspace domains, least-privilege joins, and admin notifications."""

from __future__ import annotations

import asyncio
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Protocol

import dns.exception
import dns.resolver
from sqlalchemy import and_, case, or_, select, text, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pramana_contracts import (
    CreateDomain,
    JoinRequestCreated,
    JoinRequestDecision,
    JoinRequestView,
    OrganizationDomain,
    OrganizationRole,
)

from . import ids
from .account_rows import JoinRequestRow, OrganizationDomainRow
from .auth.service import Principal
from .cursors import CursorCodec
from .db import AuditLogRow, Database, MembershipRow, OrganizationRow, UserRow, acting_for
from .errors import ApiError, not_found
from .observability import log
from .outbox import EmailEnvelope, queue_email
from .vault import MasterKey

MANAGERS = ("owner", "admin")
DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
VERIFICATION_PREFIX = "pramana-verification="
AUTO_JOIN_STEP_UP = timedelta(minutes=10)

# This list is kept current with the consumer mailbox providers offered in common signup flows.
PUBLIC_EMAIL_DOMAINS = frozenset(
    {
        "aol.com",
        "att.net",
        "comcast.net",
        "fastmail.com",
        "fastmail.fm",
        "gmail.com",
        "gmx.com",
        "gmx.de",
        "googlemail.com",
        "hotmail.com",
        "hotmail.co.in",
        "icloud.com",
        "live.com",
        "live.co.uk",
        "mail.com",
        "me.com",
        "msn.com",
        "outlook.com",
        "proton.me",
        "protonmail.com",
        "rediffmail.com",
        "tutanota.com",
        "tuta.com",
        "yahoo.com",
        "yahoo.co.in",
        "yahoo.co.uk",
        "yahoo.co.jp",
        "yahoo.fr",
        "yahoo.in",
        "ymail.com",
        "yandex.com",
        "yandex.ru",
        "zoho.com",
    }
)


class DnsTxtResolver(Protocol):
    async def lookup_txt(self, name: str) -> set[str]:
        """Return every TXT record value for a name."""


class DnsPythonResolver:
    """System DNS resolver behind an interface that tests can replace."""

    def __init__(self, timeout_s: float = 3.0) -> None:
        self.timeout_s = timeout_s

    async def lookup_txt(self, name: str) -> set[str]:
        return await asyncio.to_thread(self._lookup, name)

    def _lookup(self, name: str) -> set[str]:
        resolver = dns.resolver.Resolver()
        resolver.timeout = self.timeout_s
        resolver.lifetime = self.timeout_s
        answers = resolver.resolve(name, "TXT")
        return {
            b"".join(part for part in answer.strings).decode("utf-8", errors="replace")
            for answer in answers
        }


JOIN_NOTICE_KIND = "domain_join_notice"
"""Mail to workspace managers about a join. Sent by the relay after the join commits."""
JOIN_DECISION_KIND = "domain_join_decision"
"""Mail to the requester about their join request. Sent by the relay after the decision commits."""


def normalise_domain(value: str) -> str:
    raw = value.strip().rstrip(".").lower()
    try:
        domain = raw.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ApiError(422, "DOMAIN_INVALID", "enter a valid internet domain name") from exc
    if (
        len(domain) > 253
        or "." not in domain
        or any(not DOMAIN_LABEL.fullmatch(label) for label in domain.split("."))
    ):
        raise ApiError(422, "DOMAIN_INVALID", "enter a valid internet domain name")
    return domain


def is_public_email_domain(domain: str) -> bool:
    return any(domain == public or domain.endswith(f".{public}") for public in PUBLIC_EMAIL_DOMAINS)


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1].lower() if "@" in email else ""


def domain_view(row: OrganizationDomainRow) -> OrganizationDomain:
    is_dns = row.verification == "dns_txt" and row.verified_at is None
    return OrganizationDomain(
        domain=row.domain,
        verification=row.verification,
        verified_at=row.verified_at,
        join_policy=row.join_policy,
        verification_name=f"_pramana-verify.{row.domain}" if is_dns else None,
        verification_value=(VERIFICATION_PREFIX + row.verification_token)
        if is_dns and row.verification_token
        else None,
    )


def join_request_view(row: JoinRequestRow, org: OrganizationRow, user: UserRow) -> JoinRequestView:
    return JoinRequestView(
        id=ids.encode("join", row.id),
        organization_id=ids.encode("org", row.org_id),
        organization_name=org.name,
        requester_name=user.display_name,
        requester_email=user.email,
        status=row.status,
        role=OrganizationRole(row.roles[0]) if row.roles else None,
        decision_source=row.decision_source,
        requested_at=row.requested_at,
        decided_at=row.decided_at,
    )


class DomainJoins:
    def __init__(self, db: Database, resolver: DnsTxtResolver, master: MasterKey) -> None:
        self.db, self.resolver, self.master = db, resolver, master

    @staticmethod
    async def _lock_domain(session: AsyncSession, org_id: uuid.UUID, domain: str) -> None:
        await session.execute(
            text("select pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"workspace-domain:{org_id}:{domain}"},
        )

    async def list_domains(self, org_id: uuid.UUID) -> list[OrganizationDomain]:
        async with self.db.read() as session:
            rows = await session.scalars(
                select(OrganizationDomainRow)
                .where(OrganizationDomainRow.org_id == org_id)
                .order_by(OrganizationDomainRow.domain)
            )
        return [domain_view(row) for row in rows]

    async def add_domain(
        self, org_id: uuid.UUID, principal: Principal, body: CreateDomain
    ) -> OrganizationDomain:
        domain = normalise_domain(body.domain)
        if is_public_email_domain(domain):
            raise ApiError(
                422,
                "PUBLIC_EMAIL_DOMAIN",
                "Personal email domains such as Gmail or Outlook cannot be claimed "
                "for a workspace.",
            )
        if body.join_policy == "auto":
            self._require_fresh_google(principal)
        token = secrets.token_urlsafe(32) if body.verification == "dns_txt" else None
        async with self.db.transaction() as session:
            row = await session.scalar(
                select(OrganizationDomainRow).where(
                    OrganizationDomainRow.org_id == org_id,
                    OrganizationDomainRow.domain == domain,
                )
            )
            if row is not None:
                if row.verification != body.verification:
                    raise ApiError(
                        409,
                        "DOMAIN_ALREADY_ADDED",
                        "This domain is already set up with a different verification method.",
                    )
                return domain_view(row)
            row = OrganizationDomainRow(
                org_id=org_id,
                domain=domain,
                verification=body.verification,
                join_policy=body.join_policy,
                verification_token=token,
                added_by=principal.id,
            )
            session.add(row)
            session.add(
                self._audit(
                    org_id,
                    principal.id,
                    "domain.added",
                    domain,
                    {"verification": body.verification, "join_policy": body.join_policy},
                )
            )
            await session.flush()
            return domain_view(row)

    async def verify_domain(
        self, org_id: uuid.UUID, domain_value: str, principal: Principal
    ) -> OrganizationDomain:
        domain = normalise_domain(domain_value)
        async with self.db.read() as session:
            row = await session.scalar(
                select(OrganizationDomainRow).where(
                    OrganizationDomainRow.org_id == org_id,
                    OrganizationDomainRow.domain == domain,
                )
            )
            if row is None:
                raise not_found("domain claim")
            method, token = row.verification, row.verification_token
            if row.verified_at is not None:
                return domain_view(row)
        if method == "google_hd":
            if not (
                principal.email_verified
                and principal.auth_method == "google"
                and principal.hosted_domain
                and principal.hosted_domain.lower() == domain
                and email_domain(principal.email) == domain
            ):
                raise ApiError(
                    403,
                    "DOMAIN_IDENTITY_MISMATCH",
                    "Sign in with a verified Google Workspace address at this exact "
                    "domain to verify it.",
                )
        else:
            if token is None:
                raise ApiError(
                    409, "DOMAIN_CHALLENGE_MISSING", "create a new DNS verification record"
                )
            try:
                records = await self.resolver.lookup_txt(f"_pramana-verify.{domain}")
            except (dns.exception.DNSException, OSError, TimeoutError) as exc:
                log.warning("domain_dns_lookup_failed", error=type(exc).__name__)
                raise ApiError(
                    503,
                    "DOMAIN_DNS_UNAVAILABLE",
                    "We could not check DNS right now. Try again in a few minutes.",
                ) from exc
            if VERIFICATION_PREFIX + token not in records:
                raise ApiError(
                    422,
                    "DOMAIN_TXT_NOT_FOUND",
                    "Add the exact TXT value shown here, wait for DNS to update, then try again.",
                )
        try:
            async with self.db.transaction() as session:
                row = await session.scalar(
                    select(OrganizationDomainRow)
                    .where(
                        OrganizationDomainRow.org_id == org_id,
                        OrganizationDomainRow.domain == domain,
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                if row is None:
                    raise not_found("domain claim")
                if row.verification != method or row.verification_token != token:
                    raise ApiError(
                        409,
                        "DOMAIN_CHALLENGE_CHANGED",
                        "The domain verification changed. Check the current settings and "
                        "try again.",
                    )
                if row.verified_at is None:
                    row.verified_at = datetime.now(UTC)
                    row.verification_token = None
                    session.add(
                        self._audit(
                            org_id,
                            principal.id,
                            "domain.verified",
                            domain,
                            {"verification": method},
                        )
                    )
                await session.flush()
                return domain_view(row)
        except IntegrityError as exc:
            raise ApiError(
                409,
                "DOMAIN_ALREADY_CLAIMED",
                "This domain is already verified for another workspace.",
            ) from exc

    async def set_policy(
        self, org_id: uuid.UUID, domain_value: str, principal: Principal, policy: str
    ) -> OrganizationDomain:
        domain = normalise_domain(domain_value)
        if policy == "auto":
            self._require_fresh_google(principal)
        async with self.db.transaction() as session:
            await self._lock_domain(session, org_id, domain)
            row = await session.scalar(
                select(OrganizationDomainRow)
                .where(
                    OrganizationDomainRow.org_id == org_id,
                    OrganizationDomainRow.domain == domain,
                )
                .with_for_update()
            )
            if row is None:
                raise not_found("domain claim")
            before = row.join_policy
            row.join_policy = policy
            session.add(
                self._audit(
                    org_id,
                    principal.id,
                    "domain.join_policy_changed",
                    domain,
                    {"from": before, "to": policy},
                )
            )
            await session.flush()
            return domain_view(row)

    async def remove_domain(
        self, org_id: uuid.UUID, domain_value: str, principal: Principal
    ) -> None:
        domain = normalise_domain(domain_value)
        now = datetime.now(UTC)
        async with self.db.transaction() as session:
            await self._lock_domain(session, org_id, domain)
            row = await session.scalar(
                select(OrganizationDomainRow)
                .where(
                    OrganizationDomainRow.org_id == org_id,
                    OrganizationDomainRow.domain == domain,
                )
                .with_for_update()
            )
            if row is None:
                raise not_found("domain claim")
            pending = list(
                await session.scalars(
                    select(JoinRequestRow)
                    .join(UserRow, UserRow.id == JoinRequestRow.requester_id)
                    .where(
                        JoinRequestRow.org_id == org_id,
                        JoinRequestRow.status == "pending",
                        UserRow.email.ilike(f"%@{domain}"),
                    )
                    .with_for_update()
                )
            )
            for request in pending:
                request.status = "cancelled"
                request.decided_by = principal.id
                request.decision_source = "admin"
                request.decided_at = now
                request.updated_at = now
            await session.delete(row)
            session.add(self._audit(org_id, principal.id, "domain.removed", domain, {}))

    async def list_join_requests(
        self,
        org_id: uuid.UUID,
        principal: Principal,
        *,
        limit: int,
        cursor: str | None,
        codec: CursorCodec,
    ) -> tuple[list[JoinRequestView], str | None]:
        if not set(MANAGERS).intersection(principal.roles):
            raise ApiError(
                403, "ROLE_FORBIDDEN", "only workspace owners and admins can review join requests"
            )
        priority = case((JoinRequestRow.status == "pending", 0), else_=1)
        filters: dict[str, object] = {}
        scope = "join-requests"
        sort = codec.decode(cursor, scope=scope, org_id=str(org_id), filters=filters, sort_fields=3)
        query = (
            select(JoinRequestRow, OrganizationRow, UserRow)
            .join(OrganizationRow, OrganizationRow.id == JoinRequestRow.org_id)
            .join(UserRow, UserRow.id == JoinRequestRow.requester_id)
            .where(JoinRequestRow.org_id == org_id)
        )
        if sort is not None:
            try:
                after_priority = int(sort[0])
                after_requested_at = datetime.fromisoformat(str(sort[1]))
                after_id = uuid.UUID(str(sort[2]))
            except (TypeError, ValueError) as exc:
                raise ApiError(400, "CURSOR_INVALID", "Restart from the first page.") from exc
            if after_priority not in (0, 1):
                raise ApiError(400, "CURSOR_INVALID", "Restart from the first page.")
            query = query.where(
                or_(
                    priority > after_priority,
                    and_(
                        priority == after_priority,
                        tuple_(JoinRequestRow.requested_at, JoinRequestRow.id)
                        < tuple_(after_requested_at, after_id),
                    ),
                )
            )
        async with self.db.read() as session:
            rows = (
                await session.execute(
                    query.order_by(
                        priority.asc(), JoinRequestRow.requested_at.desc(), JoinRequestRow.id.desc()
                    ).limit(limit + 1)
                )
            ).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        views = [join_request_view(row, org, user) for row, org, user in rows]
        next_cursor = (
            codec.encode(
                scope=scope,
                org_id=str(org_id),
                filters=filters,
                sort=[
                    0 if rows[-1][0].status == "pending" else 1,
                    rows[-1][0].requested_at.isoformat(),
                    str(rows[-1][0].id),
                ],
            )
            if has_more and rows
            else None
        )
        return views, next_cursor

    async def request_join(self, principal: Principal, org_id: uuid.UUID) -> JoinRequestCreated:
        self._require_matching_google_email(principal)
        assert principal.hosted_domain is not None
        domain = principal.hosted_domain.lower()
        now = datetime.now(UTC)
        org_name = ""
        row: JoinRequestRow | None = None
        joined = False
        with acting_for(None, principal.id, hosted_domain=domain):
            async with self.db.transaction() as session:
                await self._lock_domain(session, org_id, domain)
                await session.execute(
                    text("select pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": f"join:{org_id}:{principal.id}"},
                )
                found = (
                    await session.execute(
                        select(OrganizationDomainRow, OrganizationRow)
                        .join(OrganizationRow, OrganizationRow.id == OrganizationDomainRow.org_id)
                        .where(
                            OrganizationDomainRow.org_id == org_id,
                            OrganizationDomainRow.domain == domain,
                            OrganizationDomainRow.verified_at.is_not(None),
                            OrganizationDomainRow.join_policy.in_(("request", "auto")),
                            OrganizationRow.deleted_at.is_(None),
                        )
                    )
                ).one_or_none()
                if found is None:
                    raise not_found("workspace domain")
                domain_row, organization = found
                org_name = organization.name
                membership = await session.scalar(
                    select(MembershipRow).where(
                        MembershipRow.org_id == org_id,
                        MembershipRow.user_id == principal.id,
                        MembershipRow.status == "active",
                    )
                )
                if membership is not None:
                    raise ApiError(409, "ALREADY_MEMBER", "you already belong to this workspace")
                row = await session.scalar(
                    select(JoinRequestRow)
                    .where(
                        JoinRequestRow.org_id == org_id,
                        JoinRequestRow.requester_id == principal.id,
                        JoinRequestRow.status == "pending",
                    )
                    .with_for_update()
                )
                if row is not None and domain_row.join_policy == "request":
                    return JoinRequestCreated(
                        request=await self._request_view(session, row), joined=False
                    )
                if row is not None and domain_row.join_policy == "auto":
                    # Close the old request using the requester's allowed transition, then
                    # record this new automatic decision as a separate notification event.
                    row.status = "cancelled"
                    row.decided_at = now
                    row.updated_at = now
                    row = JoinRequestRow(
                        id=ids.uuid7(),
                        org_id=org_id,
                        requester_id=principal.id,
                        status="approved",
                        roles=["viewer"],
                        decision_source="auto",
                        requested_at=now,
                        updated_at=now,
                        decided_at=now,
                    )
                    session.add(row)
                    joined = True
                elif domain_row.join_policy == "auto":
                    row = JoinRequestRow(
                        id=ids.uuid7(),
                        org_id=org_id,
                        requester_id=principal.id,
                        status="approved",
                        roles=["viewer"],
                        decision_source="auto",
                        requested_at=now,
                        updated_at=now,
                        decided_at=now,
                    )
                    session.add(row)
                    joined = True
                else:
                    row = JoinRequestRow(
                        id=ids.uuid7(),
                        org_id=org_id,
                        requester_id=principal.id,
                        status="pending",
                        roles=None,
                        decision_source=None,
                        requested_at=now,
                        updated_at=now,
                    )
                    session.add(row)
                if joined:
                    await session.execute(
                        text("select set_config('app.org_id', :org, true)"),
                        {"org": str(org_id)},
                    )
                    session.add(
                        MembershipRow(
                            org_id=org_id,
                            user_id=principal.id,
                            roles=["viewer"],
                            status="active",
                        )
                    )
                    session.add(
                        self._audit(
                            org_id,
                            principal.id,
                            "membership.domain_auto_joined",
                            principal.id,
                            {"domain": domain, "roles": ["viewer"]},
                        )
                    )
                else:
                    await session.execute(
                        text("select set_config('app.org_id', :org, true)"),
                        {"org": str(org_id)},
                    )
                    session.add(
                        self._audit(
                            org_id,
                            principal.id,
                            "membership.join_request_created",
                            ids.encode("join", row.id),
                            {"status": "pending", "domain": domain},
                        )
                    )
                if joined:
                    await self._queue_admin_notice(
                        session,
                        org_id,
                        "A new workspace member joined",
                        f"{principal.display_name} joined {org_name} as a viewer because "
                        f"{domain} uses automatic joining.",
                        now,
                    )
                else:
                    await self._queue_admin_notice(
                        session,
                        org_id,
                        f"Request to join {org_name}",
                        f"{principal.display_name} ({principal.email}) asked to join "
                        f"{org_name}. Review the request in Workspace settings.",
                        now,
                    )
                await session.flush()
                assert row is not None
                view = await self._request_view(session, row)
        return JoinRequestCreated(
            request=view,
            joined=joined,
            destination=f"/app/{organization.slug}" if joined else None,
        )

    async def cancel_request(self, principal: Principal, request_id: uuid.UUID) -> None:
        now = datetime.now(UTC)
        async with self.db.transaction() as session:
            row = await session.scalar(
                select(JoinRequestRow)
                .where(
                    JoinRequestRow.id == request_id,
                    JoinRequestRow.requester_id == principal.id,
                    JoinRequestRow.status == "pending",
                )
                .with_for_update()
            )
            if row is None:
                raise not_found("join request")
            row.status = "cancelled"
            row.updated_at = now
            row.decided_at = now
            await session.execute(
                text("select set_config('app.org_id', :org, true)"),
                {"org": str(row.org_id)},
            )
            session.add(
                self._audit(
                    row.org_id,
                    principal.id,
                    "membership.join_request_cancelled",
                    ids.encode("join", row.id),
                    {},
                )
            )

    async def decide_request(
        self,
        org_id: uuid.UUID,
        request_id: uuid.UUID,
        principal: Principal,
        decision: JoinRequestDecision | None,
    ) -> JoinRequestView:
        now = datetime.now(UTC)
        org_name = ""
        requester_email = ""
        async with self.db.transaction() as session:
            row = await session.scalar(
                select(JoinRequestRow)
                .where(
                    JoinRequestRow.id == request_id,
                    JoinRequestRow.org_id == org_id,
                    JoinRequestRow.status == "pending",
                )
                .with_for_update()
            )
            if row is None:
                raise not_found("join request")
            organization = await session.get(OrganizationRow, org_id)
            requester = await session.get(UserRow, row.requester_id)
            if organization is None or requester is None:
                raise not_found("join request")
            org_name, requester_email = organization.name, requester.email
            if decision is None:
                row.status = "declined"
                row.roles = None
                action = "membership.join_request_declined"
                text_body = (
                    f"Your request to join {org_name} was declined. Contact a workspace "
                    "admin if you think this is a mistake."
                )
                subject = f"Your request to join {org_name}"
            else:
                domain = email_domain(requester.email)
                valid_claim = await session.scalar(
                    select(OrganizationDomainRow.org_id).where(
                        OrganizationDomainRow.org_id == org_id,
                        OrganizationDomainRow.domain == domain,
                        OrganizationDomainRow.verified_at.is_not(None),
                    )
                )
                if requester.email_verified_at is None or valid_claim is None:
                    raise ApiError(
                        409,
                        "JOIN_REQUEST_IDENTITY_CHANGED",
                        "This person's verified email no longer matches the workspace domain.",
                    )
                member = await session.get(MembershipRow, (org_id, requester.id))
                if member is not None:
                    if member.status == "active":
                        raise ApiError(
                            409, "ALREADY_MEMBER", "this person is already in the workspace"
                        )
                    member.status = "active"
                    member.roles = [decision.role]
                else:
                    session.add(
                        MembershipRow(
                            org_id=org_id,
                            user_id=requester.id,
                            roles=[decision.role],
                            status="active",
                        )
                    )
                row.status = "approved"
                row.roles = [decision.role]
                action = "membership.join_request_approved"
                text_body = (
                    f"Your request to join {org_name} was approved as {decision.role}. "
                    "You can now sign in to Pramana and open the workspace."
                )
                subject = f"You joined {org_name}"
            row.decided_by = principal.id
            row.decision_source = "admin"
            row.decided_at = now
            row.updated_at = now
            session.add(
                self._audit(
                    org_id,
                    principal.id,
                    action,
                    ids.encode("join", row.id),
                    {"status": row.status, "roles": row.roles or []},
                )
            )
            queue_email(
                session,
                master=self.master,
                org_id=org_id,
                kind=JOIN_DECISION_KIND,
                envelope=EmailEnvelope(requester_email, subject, text_body),
                now=now,
            )
            await session.flush()
            view = join_request_view(row, organization, requester)
        return view

    async def auto_join_on_sign_in(self, principal: Principal) -> None:
        if not self._matching_google_email(principal):
            return
        assert principal.hosted_domain is not None
        domain = principal.hosted_domain.lower()
        now = datetime.now(UTC)
        with acting_for(None, principal.id, hosted_domain=domain):
            async with self.db.transaction() as session:
                await session.execute(
                    text("select pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": f"auto-join:{principal.id}:{domain}"},
                )
                matches = (
                    await session.execute(
                        select(
                            OrganizationDomainRow.org_id, OrganizationRow.name, OrganizationRow.slug
                        )
                        .join(OrganizationRow, OrganizationRow.id == OrganizationDomainRow.org_id)
                        .where(
                            OrganizationDomainRow.domain == domain,
                            OrganizationDomainRow.verified_at.is_not(None),
                            OrganizationDomainRow.join_policy == "auto",
                            OrganizationRow.deleted_at.is_(None),
                        )
                    )
                ).all()
                for org_id, name, _slug in matches:
                    await self._lock_domain(session, org_id, domain)
                    still_auto = await session.scalar(
                        select(OrganizationDomainRow.org_id).where(
                            OrganizationDomainRow.org_id == org_id,
                            OrganizationDomainRow.domain == domain,
                            OrganizationDomainRow.verified_at.is_not(None),
                            OrganizationDomainRow.join_policy == "auto",
                        )
                    )
                    if still_auto is None:
                        continue
                    await session.execute(
                        text("select pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                        {"key": f"join:{org_id}:{principal.id}"},
                    )
                    member = await session.get(MembershipRow, (org_id, principal.id))
                    pending = await session.scalar(
                        select(JoinRequestRow)
                        .where(
                            JoinRequestRow.org_id == org_id,
                            JoinRequestRow.requester_id == principal.id,
                            JoinRequestRow.status == "pending",
                        )
                        .with_for_update()
                    )
                    if member is not None:
                        if pending is not None:
                            pending.status = "cancelled"
                            pending.decision_source = "auto"
                            pending.decided_at = now
                            pending.updated_at = now
                        continue
                    if pending is not None:
                        pending.status = "cancelled"
                        pending.decision_source = "auto"
                        pending.decided_at = now
                        pending.updated_at = now
                    await session.execute(
                        text("select set_config('app.org_id', :org, true)"),
                        {"org": str(org_id)},
                    )
                    session.add(
                        MembershipRow(
                            org_id=org_id,
                            user_id=principal.id,
                            roles=["viewer"],
                            status="active",
                        )
                    )
                    session.add(
                        JoinRequestRow(
                            id=ids.uuid7(),
                            org_id=org_id,
                            requester_id=principal.id,
                            status="approved",
                            roles=["viewer"],
                            decision_source="auto",
                            requested_at=now,
                            updated_at=now,
                            decided_at=now,
                        )
                    )
                    session.add(
                        self._audit(
                            org_id,
                            principal.id,
                            "membership.domain_auto_joined",
                            principal.id,
                            {"domain": domain, "roles": ["viewer"]},
                        )
                    )
                    await self._queue_admin_notice(
                        session,
                        org_id,
                        "A new workspace member joined",
                        f"{principal.display_name} joined {name} as a viewer because "
                        f"{domain} uses automatic joining.",
                        now,
                    )

    async def _request_view(self, session: AsyncSession, row: JoinRequestRow) -> JoinRequestView:
        org = await session.get(OrganizationRow, row.org_id)
        user = await session.get(UserRow, row.requester_id)
        if org is None or user is None:
            raise not_found("join request")
        return join_request_view(row, org, user)

    async def _queue_admin_notice(
        self,
        session: AsyncSession,
        org_id: uuid.UUID,
        subject: str,
        body: str,
        now: datetime,
    ) -> None:
        """Queue the notice for each active manager, inside the join's own transaction."""
        await session.execute(
            text("select set_config('app.org_id', :org, true)"), {"org": str(org_id)}
        )
        addresses = (
            await session.scalars(
                select(UserRow.email)
                .join(MembershipRow, MembershipRow.user_id == UserRow.id)
                .where(
                    MembershipRow.org_id == org_id,
                    MembershipRow.status == "active",
                    MembershipRow.roles.overlap(list(MANAGERS)),
                )
            )
        ).all()
        for address in addresses:
            queue_email(
                session,
                master=self.master,
                org_id=org_id,
                kind=JOIN_NOTICE_KIND,
                envelope=EmailEnvelope(address, subject, body),
                now=now,
            )

    @staticmethod
    def _matching_google_email(principal: Principal) -> bool:
        return bool(
            principal.kind == "user"
            and principal.email_verified
            and principal.auth_method == "google"
            and principal.hosted_domain
            and principal.hosted_domain.lower() == email_domain(principal.email)
        )

    @classmethod
    def _require_matching_google_email(cls, principal: Principal) -> None:
        if not cls._matching_google_email(principal):
            raise ApiError(
                403,
                "DOMAIN_JOIN_VERIFICATION_REQUIRED",
                "Sign in with a verified Google Workspace address whose email domain "
                "matches its hosted domain.",
            )

    @staticmethod
    def _require_fresh_google(principal: Principal) -> None:
        now = datetime.now(UTC)
        authenticated = principal.authenticated_at
        if (
            principal.auth_method != "google"
            or authenticated is None
            or now - authenticated > AUTO_JOIN_STEP_UP
        ):
            raise ApiError(
                403,
                "FRESH_GOOGLE_SIGN_IN_REQUIRED",
                "Sign in with Google again before turning on automatic joining.",
            )

    @staticmethod
    def _audit(
        org_id: uuid.UUID,
        actor: str,
        action: str,
        target: str,
        details: dict[str, object],
    ) -> AuditLogRow:
        return AuditLogRow(
            id=ids.uuid7(),
            org_id=org_id,
            actor_kind="user",
            actor_id=actor,
            action=action,
            target_kind="organization_domain" if action.startswith("domain.") else "join_request",
            target_id=target,
            details=details,
        )
