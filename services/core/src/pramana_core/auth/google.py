"""Single-use browser flows and explicit Google account linking (ADR 0016)."""

from __future__ import annotations

import hmac
import secrets
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError

from .. import ids
from ..db import (
    AuditLogRow,
    AuthFlowRow,
    Database,
    MembershipRow,
    OrganizationRow,
    SessionRow,
    UserIdentityRow,
    UserRow,
)
from .oidc import GoogleOidc, OidcError, safe_next
from .service import AuthService, Principal, token_hash


class AccountExistsError(OidcError):
    """The existing account must be authenticated before linking."""


class AccountDisabledError(OidcError):
    """A suspended account cannot be reactivated by signing in again."""


class GoogleSignIn:
    def __init__(self, db: Database, oidc: GoogleOidc, auth: AuthService):
        self.db, self.oidc, self.auth = db, oidc, auth

    async def start(
        self,
        next_path: str,
        old_flow: str | None,
        session_token: str | None,
        *,
        login_hint: str | None = None,
        switch_account: bool = False,
    ) -> tuple[str, str]:
        cookie, state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(4))
        try:
            url = await self.oidc.authorization_url(
                state, nonce, verifier, login_hint=login_hint, switch_account=switch_account
            )
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
            raise OidcError("Google sign-in is unavailable") from exc
        principal = await self.auth.resolve(session_token) if session_token else None
        now = datetime.now(UTC)
        async with self.db.transaction() as session:
            await session.execute(delete(AuthFlowRow).where(AuthFlowRow.expires_at <= now))
            if old_flow:
                await session.execute(
                    delete(AuthFlowRow).where(AuthFlowRow.id_hash == token_hash(old_flow))
                )
            session.add(
                AuthFlowRow(
                    id_hash=token_hash(cookie),
                    state=state,
                    nonce=nonce,
                    pkce_verifier=verifier,
                    next_path=safe_next(next_path),
                    created_at=now,
                    expires_at=now + timedelta(minutes=10),
                    link_user_id=principal.id if principal else None,
                    link_session_hash=token_hash(session_token)
                    if principal and session_token
                    else None,
                )
            )
        return cookie, url

    async def consume(self, cookie: str | None, state: str | None) -> AuthFlowRow:
        if not cookie or len(cookie) > 256:
            raise OidcError("sign-in flow is missing")
        # DELETE RETURNING commits before any provider call, including invalid-state failures.
        async with self.db.transaction() as session:
            flow = (
                await session.execute(
                    delete(AuthFlowRow)
                    .where(AuthFlowRow.id_hash == token_hash(cookie))
                    .returning(AuthFlowRow)
                )
            ).scalar_one_or_none()
        if (
            flow is None
            or flow.expires_at <= datetime.now(UTC)
            or state is None
            or not hmac.compare_digest(flow.state.encode(), state.encode())
        ):
            raise OidcError("sign-in flow has expired")
        return flow

    async def finish(
        self,
        flow: AuthFlowRow,
        code: str,
        session_token: str | None,
        user_agent: str | None,
    ) -> tuple[str, Principal]:
        identity = await self.oidc.exchange(code, flow.pkce_verifier, flow.nonce)
        principal = await self.auth.resolve(session_token) if session_token else None
        can_link = bool(
            principal
            and session_token
            and flow.link_user_id == principal.id
            and flow.link_session_hash == token_hash(session_token)
        )
        try:
            async with self.db.transaction() as session:
                # Serialize short account mutations across instances. Never hold this over HTTP.
                await session.execute(text("select pg_advisory_xact_lock(72488601231564)"))
                linked = (
                    await session.execute(
                        select(UserIdentityRow).where(
                            UserIdentityRow.provider == "google",
                            UserIdentityRow.subject == identity.sub,
                        )
                    )
                ).scalar_one_or_none()
                action = "identity.signed_in"
                user: UserRow | None
                if linked:
                    user = (
                        await session.execute(
                            select(UserRow).where(UserRow.id == linked.user_id).with_for_update()
                        )
                    ).scalar_one()
                    if not user.active:
                        raise AccountDisabledError("account is disabled")
                    email_owner = (
                        await session.execute(
                            select(UserRow).where(
                                UserRow.email == identity.email, UserRow.id != user.id
                            )
                        )
                    ).scalar_one_or_none()
                    if email_owner is not None:
                        raise AccountExistsError("email belongs to another account")
                    if user.email != identity.email:
                        user.email = identity.email
                        user.email_verified_at = (
                            datetime.now(UTC) if identity.authoritative_email else None
                        )
                        action = "identity.email_changed"
                else:
                    user = (
                        await session.execute(
                            select(UserRow).where(UserRow.email == identity.email).with_for_update()
                        )
                    ).scalar_one_or_none()
                    if user and not user.active:
                        raise AccountDisabledError("account is disabled")
                    if user and user.email_verified_at is not None:
                        if (
                            not can_link
                            or principal is None
                            or principal.id != user.id
                            or not identity.authoritative_email
                        ):
                            raise AccountExistsError("authenticate the existing account first")
                        # Linking is a security boundary: revoke every older session for this user.
                        await session.execute(
                            delete(SessionRow).where(SessionRow.user_id == user.id)
                        )
                        action = "identity.linked"
                    elif user:
                        if not identity.authoritative_email:
                            raise AccountExistsError("verify ownership of this email first")
                        await session.execute(
                            text("select set_config('app.user_id', :u, true)"), {"u": user.id}
                        )
                        membership = (
                            await session.execute(
                                select(MembershipRow.user_id)
                                .where(MembershipRow.user_id == user.id)
                                .limit(1)
                            )
                        ).first()
                        organization = (
                            await session.execute(
                                select(OrganizationRow.id)
                                .where(OrganizationRow.created_by == user.id)
                                .limit(1)
                            )
                        ).first()
                        if membership or organization:
                            # Invalid legacy state needs an administrator, never transfer ownership.
                            raise AccountExistsError("existing account needs review")
                        await session.delete(user)
                        await session.flush()
                        user = None
                        action = "identity.replaced_unverified"
                    if user is None:
                        user = UserRow(
                            id=ids.new("usr")[1],
                            email=identity.email,
                            display_name=identity.name.strip() or identity.email.split("@")[0][:80],
                            password_hash=None,
                            roles=[],
                            active=True,
                            email_verified_at=datetime.now(UTC)
                            if identity.authoritative_email
                            else None,
                        )
                        session.add(user)
                        await session.flush()
                        if action == "identity.signed_in":
                            action = "identity.created"
                    linked = UserIdentityRow(
                        id=ids.uuid7(),
                        user_id=user.id,
                        provider="google",
                        subject=identity.sub,
                        email_at_link=identity.email,
                        hosted_domain=identity.hosted_domain,
                    )
                    session.add(linked)
                assert user is not None
                now = datetime.now(UTC)
                linked.last_used_at = now
                linked.hosted_domain = identity.hosted_domain
                if session_token:
                    await session.execute(
                        delete(SessionRow).where(SessionRow.token_hash == token_hash(session_token))
                    )
                token, resolved = await self.auth.issue_session(
                    session, user, auth_method="google", user_agent=user_agent
                )
                await session.execute(
                    text("select set_config('app.user_id', :u, true)"), {"u": user.id}
                )
                session.add(
                    AuditLogRow(
                        id=ids.uuid7(),
                        actor_kind="user",
                        actor_id=user.id,
                        action=action,
                        target_kind="identity",
                        target_id=str(linked.id),
                        details={},
                    )
                )
            return token, resolved
        except IntegrityError as exc:
            # Email and (provider, subject) constraints are the final guard against races.
            raise AccountExistsError("account changed during sign-in; try again") from exc
