"""Organization-scoped saved model loading and a bounded, content-addressed compiler cache."""

from __future__ import annotations

import asyncio
import uuid
import weakref
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from sqlalchemy import select, tuple_

from pramana_domain.spec_storage import load_spec, spec_digest
from pramana_engine import CompiledModel, compile_pack

from .cursors import CursorCodec
from .db import Database, SiteModelRow, SiteRow, current_org
from .errors import ApiError, not_found


@dataclass(frozen=True)
class PinnedModel:
    site_id: uuid.UUID
    model_id: uuid.UUID
    version: int
    spec_sha256: bytes
    compiled: CompiledModel
    documented_spec: dict[str, Any]
    sandbox: bool = False


class StoredModels:
    def __init__(self, db: Database, *, cache_limit: int = 32) -> None:
        if cache_limit < 1:
            raise ValueError("the model cache must hold at least one entry")
        self.db = db
        self.cache_limit = cache_limit
        self._compiled: OrderedDict[bytes, CompiledModel] = OrderedDict()
        self._locks: weakref.WeakValueDictionary[bytes, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

    @staticmethod
    def _org() -> uuid.UUID:
        org = current_org.get()
        if org is None:
            raise not_found("site")
        return org

    async def sites(
        self, limit: int, cursor: str | None, codec: CursorCodec
    ) -> tuple[list[SiteRow], str | None]:
        org = self._org()
        filters: dict[str, object] = {}
        sort = codec.decode(cursor, scope="sites", org_id=str(org), filters=filters)
        query = select(SiteRow).where(SiteRow.org_id == org, SiteRow.archived_at.is_(None))
        if sort is not None:
            try:
                after_created = datetime.fromisoformat(str(sort[0]))
                after_id = uuid.UUID(str(sort[1]))
            except ValueError as exc:
                raise ApiError(400, "CURSOR_INVALID", "Restart from the first page.") from exc
            query = query.where(
                tuple_(SiteRow.created_at, SiteRow.id) < tuple_(after_created, after_id)
            )
        async with self.db.read() as session:
            rows = list(
                await session.scalars(
                    query.order_by(SiteRow.created_at.desc(), SiteRow.id.desc()).limit(limit + 1)
                )
            )
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            codec.encode(
                scope="sites",
                org_id=str(org),
                filters=filters,
                sort=[rows[-1].created_at.isoformat(), str(rows[-1].id)],
            )
            if has_more and rows
            else None
        )
        return rows, next_cursor

    async def site(self, site_id: uuid.UUID) -> SiteRow:
        org = self._org()
        async with self.db.read() as session:
            site = await session.scalar(
                select(SiteRow).where(
                    SiteRow.id == site_id, SiteRow.org_id == org, SiteRow.archived_at.is_(None)
                )
            )
        if site is None:
            raise not_found("site")
        return site

    async def versions(
        self, site_id: uuid.UUID, limit: int, cursor: str | None, codec: CursorCodec
    ) -> tuple[list[SiteModelRow], str | None]:
        site = await self.site(site_id)
        filters: dict[str, object] = {}
        scope = f"models:{site_id}"
        sort = codec.decode(cursor, scope=scope, org_id=str(site.org_id), filters=filters)
        query = select(SiteModelRow).where(
            SiteModelRow.org_id == site.org_id,
            SiteModelRow.site_id == site.id,
            SiteModelRow.status.in_(("published", "retired")),
        )
        if sort is not None:
            try:
                after_created = datetime.fromisoformat(str(sort[0]))
                after_id = uuid.UUID(str(sort[1]))
            except ValueError as exc:
                raise ApiError(400, "CURSOR_INVALID", "Restart from the first page.") from exc
            query = query.where(
                tuple_(SiteModelRow.created_at, SiteModelRow.id) < tuple_(after_created, after_id)
            )
        async with self.db.read() as session:
            rows = list(
                await session.scalars(
                    query.order_by(SiteModelRow.created_at.desc(), SiteModelRow.id.desc()).limit(
                        limit + 1
                    )
                )
            )
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            codec.encode(
                scope=scope,
                org_id=str(site.org_id),
                filters=filters,
                sort=[rows[-1].created_at.isoformat(), str(rows[-1].id)],
            )
            if has_more and rows
            else None
        )
        return rows, next_cursor

    async def row(
        self, site_id: uuid.UUID, model_id: uuid.UUID, *, allow_draft: bool = False
    ) -> SiteModelRow:
        org = self._org()
        async with self.db.read() as session:
            model = await session.scalar(
                select(SiteModelRow).where(
                    SiteModelRow.id == model_id,
                    SiteModelRow.site_id == site_id,
                    SiteModelRow.org_id == org,
                    SiteModelRow.status.in_(
                        ("published", "retired", "draft")
                        if allow_draft
                        else ("published", "retired")
                    ),
                )
            )
        if model is None:
            raise not_found("site model")
        return model

    async def load(self, site_id: uuid.UUID, model_id: uuid.UUID) -> PinnedModel:
        # The explicit org query precedes any cache lookup, including with a privileged test role.
        row = await self.row(site_id, model_id)
        if spec_digest(row.spec) != row.spec_sha256:
            raise ApiError(
                503, "MODEL_INTEGRITY_ERROR", "the saved model failed its integrity check"
            )
        digest = row.spec_sha256
        lock = self._locks.setdefault(digest, asyncio.Lock())
        async with lock:
            compiled = self._compiled.get(digest)
            if compiled is None:
                try:
                    pack = load_spec(row.spec)
                    compiled = await asyncio.to_thread(compile_pack, pack)
                except ValueError as exc:
                    raise ApiError(
                        503, "MODEL_INVALID", "the saved model could not be loaded"
                    ) from exc
                self._compiled[digest] = compiled
                while len(self._compiled) > self.cache_limit:
                    self._compiled.popitem(last=False)
            self._compiled.move_to_end(digest)
        return PinnedModel(site_id, model_id, row.version, digest, compiled, row.spec)

    async def pin(self, site_id: uuid.UUID, *, practice: bool = False) -> PinnedModel:
        site = await self.site(site_id)
        if site.mode != "sandbox" and not practice:
            raise ApiError(
                409,
                "LIVE_NOT_CONFIGURED",
                "investigations with real people need calls and messages, which are not set up "
                "yet; run a practice investigation on this site's model instead",
            )
        if site.current_model_id is None:
            raise ApiError(
                409, "MODEL_REQUIRED", "publish a model before starting an investigation"
            )
        row = await self.row(site.id, site.current_model_id, allow_draft=True)
        if row.status != "published":
            raise ApiError(409, "MODEL_NOT_PUBLISHED", "choose a published model before starting")
        pinned = await self.load(site.id, row.id)
        return replace(pinned, sandbox=site.mode == "sandbox")
