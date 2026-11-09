"""Scoped idempotent route middleware with an atomic response/business transaction.

The pending claim is visible to other instances. The working transaction locks that claim and
joins the service's Database transactions, so a lost response can be replayed after one commit.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal, TypeVar, cast

import anyio
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response
from fastapi.routing import APIRoute
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException

from . import ids
from .account_rows import IdempotencyRow
from .auth.deps import current_principal
from .db import Database, acting_for, current_actor, current_org, current_user
from .errors import ApiError
from .org_access import require_organization, require_user

LEASE = timedelta(seconds=60)
RETENTION = timedelta(hours=72)
MAX_BODY = 4 * 1024 * 1024
RESPONSE_HEADERS = frozenset(
    {"content-type", "content-language", "etag", "location", "cache-control"}
)
F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class MutationPolicy:
    scope: Literal["user", "org"]
    roles: tuple[str, ...] = ()
    verified: bool = False
    participants: bool = False


def idempotent(
    scope: Literal["user", "org"], *, roles: tuple[str, ...] = (), verified: bool = False
) -> Callable[[F], F]:
    def decorate(endpoint: F) -> F:
        endpoint.__dict__["pramana_mutation"] = MutationPolicy(scope, roles, verified)
        return endpoint

    return decorate


def parse_key(value: str | None) -> str:
    if value is None:
        raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "send an Idempotency-Key for this action")
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    if not re.fullmatch(r"[A-Za-z0-9_-]{16,128}", value):
        raise ApiError(
            400,
            "IDEMPOTENCY_KEY_INVALID",
            "the Idempotency-Key must contain 16 to 128 letters, digits, underscores or hyphens",
        )
    return value


async def buffered_request(request: Request) -> tuple[Request, bytes]:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY:
            raise ApiError(413, "BODY_TOO_LARGE", "this request is too large")
        chunks.append(chunk)
    body = b"".join(chunks)
    sent = False

    async def receive() -> Any:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await request.receive()

    return Request(request.scope, receive), body


def fingerprint(request: Request, body: bytes) -> bytes:
    content_type = request.headers.get("content-type", "").partition(";")[0].lower()
    if body and (content_type == "application/json" or content_type.endswith("+json")):
        try:
            body = json.dumps(
                json.loads(body),
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        except (ValueError, UnicodeError) as exc:
            raise ApiError(422, "VALIDATION_ERROR", "request JSON is invalid") from exc
    target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return hashlib.sha256(request.method.encode() + b"\n" + target.encode() + b"\n" + body).digest()


def _where(scope: str, principal: str, key: str) -> tuple[Any, ...]:
    return (
        IdempotencyRow.scope == scope,
        IdempotencyRow.principal == principal,
        IdempotencyRow.key == key,
    )


_SEALED_RESPONSE = b"pramana-sealed-response-v1:"


def _response_context(row: IdempotencyRow) -> bytes:
    return json.dumps([row.scope, row.principal, row.key], separators=(",", ":")).encode()


def _replay(row: IdempotencyRow, request: Request) -> Response:
    assert row.response_status is not None
    body = row.response_body or b""
    if body.startswith(_SEALED_RESPONSE):
        body = request.app.state.vault.master.open_response(
            body[len(_SEALED_RESPONSE) :], _response_context(row)
        )
    return Response(
        body,
        status_code=row.response_status,
        headers={**row.response_headers, "Idempotent-Replayed": "true"},
    )


def _in_flight() -> ApiError:
    return ApiError(
        409, "IDEMPOTENCY_IN_FLIGHT", "this action is still running; retry with the same key"
    )


def _lock_conflict(exc: DBAPIError) -> bool:
    return getattr(exc.orig, "sqlstate", None) == "55P03"


async def reap_expired(db: Database) -> int:
    """Reap records visible in the caller's authenticated scope, never active row locks."""
    user, org = current_user.get(), current_org.get()
    actor = current_actor.get() or (f"user:{user}" if user else "")
    if not actor:
        return 0
    async with db.transaction() as session:
        now = (await session.execute(select(func.now()))).scalar_one()
        expired = (
            select(IdempotencyRow.scope, IdempotencyRow.principal, IdempotencyRow.key)
            .where(
                IdempotencyRow.principal == actor,
                IdempotencyRow.org_id == org
                if org is not None
                else (IdempotencyRow.org_id.is_(None) & (IdempotencyRow.scope == f"user:{user}")),
                IdempotencyRow.created_at < now - RETENTION,
                (IdempotencyRow.locked_until.is_(None) | (IdempotencyRow.locked_until < now)),
            )
            .with_for_update(skip_locked=True)
        )
        keys = list((await session.execute(expired)).all())
        for scope, principal, key in keys:
            await session.execute(delete(IdempotencyRow).where(*_where(scope, principal, key)))
        return len(keys)


class IdempotencyRoute(APIRoute):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.endpoint.__dict__.get("pramana_mutation") is not None:
            self.openapi_extra = {
                **(self.openapi_extra or {}),
                "parameters": [
                    *[
                        p
                        for p in (self.openapi_extra or {}).get("parameters", [])
                        if p.get("name", "").lower() != "idempotency-key"
                    ],
                    {
                        "name": "Idempotency-Key",
                        "in": "header",
                        "required": True,
                        "schema": {"type": "string", "minLength": 16, "maxLength": 130},
                        "description": "Reuse this key only when retrying the same action.",
                    },
                ],
                "responses": {
                    **(self.openapi_extra or {}).get("responses", {}),
                    "400": {"description": "Missing or invalid idempotency key"},
                    "409": {"description": "Action in flight or business conflict"},
                    "422": {"description": "Changed request for the same key or invalid input"},
                },
            }

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original = super().get_route_handler()
        policy = cast(MutationPolicy | None, self.endpoint.__dict__.get("pramana_mutation"))
        if policy is None:
            return original

        async def handle(request: Request) -> Response:
            principal = await current_principal(request)
            org_id: uuid.UUID | None = None
            if principal.kind == "participant":
                if (
                    policy.scope != "org"
                    or not policy.participants
                    or not getattr(request.state, "participant_authorized", False)
                    or not principal.token_id
                    or current_org.get() is None
                ):
                    raise ApiError(403, "ROLE_FORBIDDEN", "this link cannot perform this action")
                org_id = current_org.get()
                actor = f"participant:{principal.token_id}"
                user_id = None
            else:
                principal = await require_user(request, verified=policy.verified)
                if policy.scope == "org":
                    access = await require_organization(request, principal, policy.roles)
                    request.state.organization = access
                    org_id = access.organization.id
                actor = f"user:{principal.id}"
                user_id = principal.id
            scope = f"org:{org_id}" if org_id else actor
            key = parse_key(request.headers.get("idempotency-key"))
            request, body = await buffered_request(request)
            digest = fingerprint(request, body)
            db: Database = request.app.state.db
            nonce = ids.uuid7()
            with acting_for(org_id, user_id, actor=actor):
                await reap_expired(db)
                async with db.transaction() as session:
                    now = (await session.execute(select(func.now()))).scalar_one()
                    created = (
                        await session.execute(
                            insert(IdempotencyRow)
                            .values(
                                scope=scope,
                                principal=actor,
                                key=key,
                                org_id=org_id,
                                method=request.method,
                                path=request.url.path,
                                request_sha256=digest,
                                owner_nonce=nonce,
                                locked_until=now + LEASE,
                                response_headers={},
                            )
                            .on_conflict_do_nothing()
                            .returning(IdempotencyRow.key)
                        )
                    ).scalar_one_or_none()
                    if created is None:
                        row = (
                            await session.execute(
                                select(IdempotencyRow).where(*_where(scope, actor, key))
                            )
                        ).scalar_one()
                        if row.request_sha256 != digest:
                            raise ApiError(
                                422,
                                "IDEMPOTENCY_KEY_REUSED",
                                "use a new key for a different action",
                            )
                        if row.response_status is not None:
                            return _replay(row, request)
                        if row.locked_until is not None and row.locked_until > now:
                            raise _in_flight()
                        try:
                            row = (
                                await session.execute(
                                    select(IdempotencyRow)
                                    .where(*_where(scope, actor, key))
                                    .with_for_update(nowait=True)
                                    .execution_options(populate_existing=True)
                                )
                            ).scalar_one()
                        except DBAPIError as exc:
                            if _lock_conflict(exc):
                                raise _in_flight() from exc
                            raise
                        if row.response_status is not None:
                            return _replay(row, request)
                        row.owner_nonce, row.locked_until = nonce, now + LEASE
                try:
                    async with db.unit_of_work() as session:
                        row = (
                            await session.execute(
                                select(IdempotencyRow)
                                .where(*_where(scope, actor, key))
                                .with_for_update(nowait=True)
                            )
                        ).scalar_one()
                        if row.owner_nonce != nonce:
                            raise _in_flight()
                        savepoint = await session.begin_nested()
                        before = set(session.info.get("appended_investigations", set()))
                        try:
                            response = await original(request)
                        except (ApiError, RequestValidationError, HTTPException) as exc:
                            await savepoint.rollback()
                            session.info["appended_investigations"] = before
                            error_type = (
                                ApiError
                                if isinstance(exc, ApiError)
                                else RequestValidationError
                                if isinstance(exc, RequestValidationError)
                                else HTTPException
                            )
                            renderer = cast(
                                Callable[[Request, Exception], Awaitable[Response]],
                                request.app.exception_handlers[error_type],
                            )
                            response = await renderer(request, exc)
                        else:
                            if response.status_code >= 400:
                                await savepoint.rollback()
                                session.info["appended_investigations"] = before
                            else:
                                await savepoint.commit()
                        if not hasattr(response, "body"):
                            raise RuntimeError("idempotent commands must return a bounded response")
                        row.response_status = response.status_code
                        row.response_body = bytes(response.body)
                        if (
                            request.url.path.endswith("/consent-requests")
                            and response.status_code < 400
                        ):
                            row.response_body = (
                                _SEALED_RESPONSE
                                + request.app.state.vault.master.seal_response(
                                    row.response_body, _response_context(row)
                                )
                            )
                        row.response_headers = {
                            k: v for k, v in response.headers.items() if k in RESPONSE_HEADERS
                        }
                        row.owner_nonce = None
                        row.locked_until = None
                    return response
                except BaseException as exc:
                    # Cancellation must not leave a pending claim behind until its lease expires.
                    with anyio.CancelScope(shield=True):
                        async with db.transaction() as session:
                            owned = (
                                await session.execute(
                                    select(IdempotencyRow)
                                    .where(
                                        *_where(scope, actor, key),
                                        IdempotencyRow.owner_nonce == nonce,
                                        IdempotencyRow.response_status.is_(None),
                                    )
                                    .with_for_update(skip_locked=True)
                                )
                            ).scalar_one_or_none()
                            if owned is not None:
                                await session.execute(
                                    delete(IdempotencyRow).where(
                                        *_where(scope, actor, key),
                                        IdempotencyRow.owner_nonce == nonce,
                                        IdempotencyRow.response_status.is_(None),
                                    )
                                )
                    if isinstance(exc, DBAPIError) and _lock_conflict(exc):
                        raise _in_flight() from exc
                    raise

        return handle
