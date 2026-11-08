"""Stored site models compile identically and cannot escape their organization context."""

from __future__ import annotations

import asyncio
import copy
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pytest
from core_testkit import truncate_all
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from pramana_core import ids
from pramana_core.account_rows import ModelTemplateRow
from pramana_core.db import Database, OrganizationRow, SiteModelRow, SiteRow, acting_for
from pramana_core.errors import ApiError
from pramana_core.site_models import StoredModels
from pramana_domain import DomainPack, load_pack
from pramana_domain.spec_storage import canonical_spec, load_spec, spec_digest
from pramana_engine import compile_pack

pytestmark = pytest.mark.db


@asynccontextmanager
async def database(url: str) -> AsyncIterator[Database]:
    db = Database(create_async_engine(url))
    try:
        yield db
    finally:
        await db.dispose()


async def seed(url: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    async with database(url) as db, db.transaction() as session:
        spec = (await session.scalars(select(ModelTemplateRow))).first()
        assert spec is not None
        reference = copy.deepcopy(spec.spec)
        result["reference"] = reference
        for label in ("a", "b"):
            org = OrganizationRow(id=ids.uuid7(), slug=f"stored-{label}", name=label, kind="campus")
            session.add(org)
            await session.flush()
            result[f"org_{label}"] = org.id
            for kind in (
                (
                    "original",
                    "different",
                    "third",
                    "draft",
                    "retired",
                    "empty",
                    "live",
                    "corrupt",
                    "invalid",
                )
                if label == "a"
                else ("original",)
            ):
                site = SiteRow(
                    id=ids.uuid7(),
                    org_id=org.id,
                    name=kind,
                    kind="hostel",
                    mode="live" if kind == "live" else "sandbox",
                )
                session.add(site)
                await session.flush()
                result[f"{label}_{kind}_site"] = site.id
                if kind in ("empty", "live"):
                    continue
                value = copy.deepcopy(reference)
                if kind in ("different", "third"):
                    component = next(c for c in value["components"] if c["failure_modes"])
                    component["failure_modes"][0]["prior"] *= 0.5 if kind == "different" else 0.25
                if kind == "invalid":
                    value["components"] = []
                digest = spec_digest(value)
                model = SiteModelRow(
                    id=ids.uuid7(),
                    org_id=org.id,
                    site_id=site.id,
                    version=1,
                    status=kind if kind in ("draft", "retired") else "published",
                    spec=value,
                    spec_sha256=b"x" * 32 if kind == "corrupt" else digest,
                    published_at=None if kind == "draft" else datetime.now(UTC),
                )
                session.add(model)
                await session.flush()
                site.current_model_id = model.id
                result[f"{label}_{kind}_model"] = model.id
    return result


@pytest.fixture(params=["owner", "runtime"])
def model_data(request: pytest.FixtureRequest, migrated_db: str) -> tuple[str, dict[str, Any]]:
    asyncio.run(truncate_all(migrated_db))
    data = asyncio.run(seed(migrated_db))
    url = migrated_db
    if request.param == "runtime":
        url = (
            make_url(url)
            .set(username="pramana_app", password=None)
            .render_as_string(hide_password=False)
        )
    return url, data


def run(model_data: tuple[str, dict[str, Any]], check: Callable[..., Any]) -> None:
    url, data = model_data

    async def go() -> None:
        async with database(url) as db:
            await check(StoredModels(db, cache_limit=2), data)

    asyncio.run(go())


def test_saved_reference_matches_file_compilation_exactly(
    model_data: tuple[str, dict[str, Any]],
) -> None:
    async def check(store: StoredModels, data: dict[str, Any]) -> None:
        with acting_for(data["org_a"]):
            saved = await store.pin(data["a_original_site"])
        reference = compile_pack(load_pack("campus_block_c"))
        assert saved.compiled.hypotheses == reference.hypotheses
        for name in ("prior", "predictions", "decision_of", "loss"):
            assert np.array_equal(getattr(saved.compiled, name), getattr(reference, name))
        assert saved.spec_sha256 == spec_digest(data["reference"])
        assert saved.model_id == data["a_original_model"]

    run(model_data, check)


def test_same_pack_label_different_spec_never_shares_compilation(
    model_data: tuple[str, dict[str, Any]],
) -> None:
    async def check(store: StoredModels, data: dict[str, Any]) -> None:
        with acting_for(data["org_a"]):
            original = await store.pin(data["a_original_site"])
            changed = await store.pin(data["a_different_site"])
        assert original.compiled.pack.pack == changed.compiled.pack.pack
        assert original.spec_sha256 != changed.spec_sha256
        assert not np.array_equal(original.compiled.prior, changed.compiled.prior)
        assert len(store._compiled) == 2
        with acting_for(data["org_b"]):
            same = await store.pin(data["b_original_site"])
        assert same.compiled is original.compiled

    run(model_data, check)


def test_no_context_or_wrong_org_cannot_read_even_a_cached_model(
    model_data: tuple[str, dict[str, Any]],
) -> None:
    async def check(store: StoredModels, data: dict[str, Any]) -> None:
        with acting_for(data["org_a"]):
            await store.pin(data["a_original_site"])
        for org in (None, data["org_b"]):
            with acting_for(org):
                with pytest.raises(ApiError) as error:
                    await store.load(data["a_original_site"], data["a_original_model"])
                assert error.value.status == 404
        with acting_for(data["org_a"]):
            with pytest.raises(ApiError) as error:
                await store.load(data["a_different_site"], data["a_original_model"])
            assert error.value.status == 404

    run(model_data, check)


@pytest.mark.parametrize(
    ("kind", "code"),
    [
        ("empty", "MODEL_REQUIRED"),
        ("live", "LIVE_NOT_CONFIGURED"),
        ("draft", "MODEL_NOT_PUBLISHED"),
        ("retired", "MODEL_NOT_PUBLISHED"),
        ("corrupt", "MODEL_INTEGRITY_ERROR"),
        ("invalid", "MODEL_INVALID"),
    ],
)
def test_unusable_models_fail_before_investigation_creation(
    model_data: tuple[str, dict[str, Any]], kind: str, code: str
) -> None:
    async def check(store: StoredModels, data: dict[str, Any]) -> None:
        with acting_for(data["org_a"]):
            with pytest.raises(ApiError) as error:
                await store.pin(data[f"a_{kind}_site"])
            assert error.value.code == code

    run(model_data, check)


def test_concurrent_loads_compile_once(
    model_data: tuple[str, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def compile_once(pack: DomainPack) -> Any:
        nonlocal calls
        calls += 1
        return compile_pack(pack)

    monkeypatch.setattr("pramana_core.site_models.compile_pack", compile_once)

    async def check(store: StoredModels, data: dict[str, Any]) -> None:
        with acting_for(data["org_a"]):
            rows = await asyncio.gather(*(store.pin(data["a_original_site"]) for _ in range(5)))
        assert calls == 1
        assert all(x.compiled is rows[0].compiled for x in rows)

    run(model_data, check)


def test_retired_pin_and_cold_rebuild_preserve_the_saved_version(
    model_data: tuple[str, dict[str, Any]],
) -> None:
    async def check(store: StoredModels, data: dict[str, Any]) -> None:
        with acting_for(data["org_a"]):
            old = await store.load(data["a_retired_site"], data["a_retired_model"])
            fresh_store = StoredModels(store.db)
            rebuilt = await fresh_store.load(data["a_retired_site"], data["a_retired_model"])
        assert old.compiled is not rebuilt.compiled
        assert old.model_id == rebuilt.model_id
        for name in ("prior", "predictions", "decision_of", "loss"):
            assert np.array_equal(getattr(old.compiled, name), getattr(rebuilt.compiled, name))

    run(model_data, check)


def test_cache_evicts_least_recently_used_spec_without_invalidating_a_pin(
    model_data: tuple[str, dict[str, Any]],
) -> None:
    async def check(store: StoredModels, data: dict[str, Any]) -> None:
        with acting_for(data["org_a"]):
            original = await store.pin(data["a_original_site"])
            different = await store.pin(data["a_different_site"])
            assert (await store.pin(data["a_original_site"])).compiled is original.compiled
            third = await store.pin(data["a_third_site"])
            assert list(store._compiled) == [original.spec_sha256, third.spec_sha256]
            different_rebuilt = await store.pin(data["a_different_site"])
        assert different.compiled is not different_rebuilt.compiled
        assert np.array_equal(different.compiled.prior, different_rebuilt.compiled.prior)
        assert len(store._compiled) == 2

    run(model_data, check)


def test_stored_field_names_and_aliases_load_without_rewriting_bytes() -> None:
    pack = load_pack("campus_block_c")
    stored = pack.model_dump(mode="json")
    aliased = pack.model_dump(mode="json", by_alias=True)
    before = canonical_spec(stored)
    assert load_spec(stored) == load_spec(aliased) == pack
    assert canonical_spec(stored) == before
    duplicate = copy.deepcopy(stored)
    duplicate["probes"][0]["class"] = duplicate["probes"][0]["probe_class"]
    with pytest.raises(ValueError):
        load_spec(duplicate)


def test_spec_bytes_ignore_object_key_order_and_reject_nan() -> None:
    assert canonical_spec({"b": 2, "a": "हिंदी"}) == canonical_spec({"a": "हिंदी", "b": 2})
    with pytest.raises(ValueError):
        canonical_spec({"value": float("nan")})
