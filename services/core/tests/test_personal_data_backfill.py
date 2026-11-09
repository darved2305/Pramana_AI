"""Older site rows are sealed in batches without changing deterministic replay."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from auth_testkit import CSRF
from fastapi.testclient import TestClient
from participant_bot import run_to_conclusion
from sqlalchemy.ext.asyncio import create_async_engine
from test_accounts import account_core as account_core
from test_google_auth import sql
from test_personal_data import post
from test_practice import published_water_site
from test_practice import request as practice_request

from pramana_core import ids
from pramana_core.backfill import BackfillCounts, backfill_personal_data
from pramana_core.db import Database

pytestmark = pytest.mark.db

OLD_NAME = "Legacy Backfill Asha 84F2"
OLD_REPORT = "Doosre floor pe paani nahi aa raha. Legacy report marker 84F2"
OLD_TRANSCRIPT = "Legacy transcript marker 84F2 from an older investigation"


class Scoped:
    def __init__(self, client: TestClient, root: str) -> None:
        self.client = client
        self.root = root

    def post(self, path: str, **kwargs: Any) -> Any:
        headers = {**CSRF, "Idempotency-Key": uuid.uuid4().hex, **kwargs.pop("headers", {})}
        return self.client.post(
            path.replace("/v1/investigations", self.root), headers=headers, **kwargs
        )

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.client.get(path.replace("/v1/investigations", self.root), **kwargs)


def test_pre_0016_plaintext_is_sealed_and_exact_replay_survives(
    account_core: TestClient, migrated_db: str
) -> None:
    client = account_core
    workspace, investigation_root = published_water_site(client)
    org = workspace["organization"]["slug"]
    site = workspace["live_site"]["id"]
    site_name = "Legacy Directory Name 84F2"
    sql(
        migrated_db,
        "update site_people set spec = jsonb_set(spec, '{display_name}', "
        "to_jsonb(cast(:name as text))), "
        "display_name_enc = null where org_id = :org and site_id = :site and id = 'p_asha'",
        {
            "name": site_name,
            "org": ids.decode("org", workspace["organization"]["id"]),
            "site": ids.decode("site", site),
        },
    )

    service = client.app.state.investigations
    vault = service.vault
    assert vault is not None
    # This reproduces the pre-0016 write path: plaintext request, events and observation rows.
    service.vault = None
    request = practice_request(site, "VALVE_F2.closed", practice=True)
    request["participants"] = [
        {**person, "display_name": f"{OLD_NAME} {person['id']}"}
        for person in request["participants"]
    ]
    request["report"]["text"] = OLD_REPORT
    started = post(client, investigation_root, request)
    assert started.status_code == 201, started.text
    initial = started.json()
    assert initial["report"]["text"] == OLD_REPORT
    assert initial["participants"][0]["display_name"].startswith(OLD_NAME)

    scoped = Scoped(client, investigation_root)
    with TestClient(client.app.state.sim._http._transport.app) as sim:
        final, _ = run_to_conclusion(scoped, sim, initial)  # type: ignore[arg-type]
    assert final["observations"]
    transcript_row = sql(
        migrated_db,
        "select id from observations where investigation_id = :id "
        "and transcript is not null order by committed_at limit 1",
        {"id": final["id"]},
    )[0]
    sql(
        migrated_db,
        "update observations set transcript = :transcript where id = :id",
        {"transcript": OLD_TRANSCRIPT, "id": transcript_row["id"]},
    )
    sql(
        migrated_db,
        "update events set payload = jsonb_set(payload, '{extraction,evidence}', "
        "jsonb_build_array(cast(:transcript as text))) where investigation_id = :id "
        "and payload ->> 'observation_id' = :observation_id",
        {
            "transcript": OLD_TRANSCRIPT,
            "id": final["id"],
            "observation_id": transcript_row["id"],
        },
    )
    assert post(client, f"{investigation_root}/{final['id']}/reveal").status_code == 200
    before = client.get(f"{investigation_root}/{final['id']}/replay").json()
    assert before["identical"] is True
    assert before["log_intact"] is True

    async def run_backfill() -> BackfillCounts:
        db = Database(create_async_engine(migrated_db))
        try:
            return await backfill_personal_data(db, vault, batch_size=2)
        finally:
            await db.dispose()

    first = client.portal.call(run_backfill)
    assert first.directory_names == 1
    assert first.investigation_names == len(request["participants"])
    assert first.reports == 1
    assert first.transcripts >= 1
    assert first.events_sanitized > 0
    assert first.log_seals_rehashed == 1

    service.vault = vault
    after = client.get(f"{investigation_root}/{final['id']}/replay").json()
    assert after["identical"] is True
    assert after["log_intact"] is True
    assert after["replayed_sha256"] == before["replayed_sha256"]
    restored = client.get(f"{investigation_root}/{final['id']}").json()
    assert restored["report"]["text"] == OLD_REPORT
    assert restored["participants"][0]["display_name"].startswith(OLD_NAME)
    assert any(item["transcript"] == OLD_TRANSCRIPT for item in restored["observations"])
    directory = client.get(f"/v1/orgs/{org}/sites/{site}/people").json()["items"]
    assert (
        next(p for p in directory if p["person"]["id"] == "p_asha")["person"]["display_name"]
        == site_name
    )

    raw_request = sql(
        migrated_db,
        "select request::text as request from investigations where id = :id",
        {"id": final["id"]},
    )[0]["request"]
    assert OLD_REPORT not in raw_request
    assert OLD_NAME not in raw_request
    assert '"text": "-"' in raw_request
    event_rows = sql(
        migrated_db,
        "select type, payload::text as payload from events where investigation_id = :id",
        {"id": final["id"]},
    )
    assert all(OLD_REPORT not in row["payload"] for row in event_rows)
    assert all(OLD_TRANSCRIPT not in row["payload"] for row in event_rows)
    name_leaks = [row["type"] for row in event_rows if OLD_NAME in row["payload"]]
    assert name_leaks == [], name_leaks
    assert (
        sql(
            migrated_db,
            "select transcript from observations where investigation_id = :id "
            "and transcript is not null",
            {"id": final["id"]},
        )
        == []
    )
    ciphertexts = sql(
        migrated_db,
        "select ciphertext from personal_texts where investigation_id = :id",
        {"id": final["id"]},
    )
    assert ciphertexts
    assert all(OLD_REPORT.encode() not in bytes(row["ciphertext"]) for row in ciphertexts)
    assert all(OLD_NAME.encode() not in bytes(row["ciphertext"]) for row in ciphertexts)

    second = client.portal.call(run_backfill)
    assert second == BackfillCounts()
    repeated = client.get(f"{investigation_root}/{final['id']}/replay").json()
    assert repeated["replayed_sha256"] == before["replayed_sha256"]
    assert repeated["log_intact"] is True


def test_backfill_is_safe_on_an_empty_database(core: TestClient) -> None:
    async def run() -> BackfillCounts:
        return await backfill_personal_data(core.app.state.db, core.app.state.vault, batch_size=2)

    assert core.portal.call(run) == BackfillCounts()
