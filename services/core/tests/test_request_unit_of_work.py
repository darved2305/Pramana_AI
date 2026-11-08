"""A response transaction never shares its session with a child task or notifies early."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from core_testkit import DEMO_ORG_ID, body
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from pramana_core.db import Database, EventRow, acting_for

pytestmark = pytest.mark.db


def test_event_keys_are_unique_per_investigation(core: TestClient) -> None:
    first = core.post("/v1/investigations", json=body()).json()["id"]
    second = core.post("/v1/investigations", json=body()).json()["id"]
    db: Database = core.app.state.db  # type: ignore[union-attr]

    async def append(inv_id: str) -> None:
        with acting_for(uuid.UUID(DEMO_ORG_ID)):
            async with db.transaction() as session:
                session.add(
                    EventRow(
                        investigation_id=inv_id,
                        type="test.key",
                        payload={},
                        idempotency_key="same-key-for-different-investigations",
                    )
                )

    assert core.portal is not None
    core.portal.call(append, first)
    core.portal.call(append, second)
    with pytest.raises(DBAPIError, match="duplicate key"):
        core.portal.call(append, first)


def test_joined_flush_notifies_only_after_commit_and_rollback_stays_silent(
    core: TestClient,
) -> None:
    response = core.post("/v1/investigations", json=body())
    assert response.status_code == 201, response.text
    inv_id = response.json()["id"]
    db: Database = core.app.state.db  # type: ignore[union-attr]
    notifications: list[set[str]] = []
    db.commit_listeners.append(
        lambda touched: notifications.append(set(touched)) if touched else None
    )

    async def check() -> None:
        with acting_for(uuid.UUID(DEMO_ORG_ID)):
            async with db.unit_of_work() as outer:
                async with db.transaction() as joined:
                    assert joined is outer
                    joined.add(EventRow(investigation_id=inv_id, type="test.commit", payload={}))
                assert notifications == []
                async with db.read() as reader:
                    assert reader is outer
                    assert (
                        await reader.scalar(
                            select(func.count())
                            .select_from(EventRow)
                            .where(EventRow.type == "test.commit")
                        )
                        == 1
                    )

                async def child_read() -> None:
                    async with db.read() as reader:
                        assert reader is not outer
                        assert (
                            await reader.scalar(
                                select(func.count())
                                .select_from(EventRow)
                                .where(EventRow.type == "test.commit")
                            )
                            == 0
                        )

                await asyncio.create_task(child_read())
            assert notifications == [{inv_id}]

            async def rollback() -> None:
                async with db.unit_of_work():
                    async with db.transaction() as joined:
                        joined.add(
                            EventRow(investigation_id=inv_id, type="test.rollback", payload={})
                        )
                    raise ValueError("rollback")

            with pytest.raises(ValueError, match="rollback"):
                await rollback()
            assert notifications == [{inv_id}]
            async with db.read() as reader:
                assert (
                    await reader.scalar(
                        select(func.count())
                        .select_from(EventRow)
                        .where(EventRow.type == "test.rollback")
                    )
                    == 0
                )

    assert core.portal is not None
    core.portal.call(check)


def test_nested_context_clears_empty_values_and_pool_does_not_keep_them(core: TestClient) -> None:
    db: Database = core.app.state.db  # type: ignore[union-attr]
    query = text(
        "select current_setting('app.org_id',true), current_setting('app.user_id',true), "
        "current_setting('app.principal',true)"
    )

    async def check() -> None:
        with acting_for(uuid.UUID(DEMO_ORG_ID), "test-user"):
            async with db.unit_of_work():
                async with db.read() as session:
                    assert tuple((await session.execute(query)).one()) == (
                        DEMO_ORG_ID,
                        "test-user",
                        "user:test-user",
                    )
                with acting_for(None):
                    async with db.read() as session:
                        assert tuple((await session.execute(query)).one()) == (
                            "",
                            "test-user",
                            "user:test-user",
                        )
                async with db.transaction() as session:
                    assert (await session.execute(query)).one()[0] == DEMO_ORG_ID
        async with db.read() as session:
            assert tuple((await session.execute(query)).one()) == ("", "", "")

    assert core.portal is not None
    core.portal.call(check)
