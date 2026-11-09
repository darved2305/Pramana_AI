"""Give every workspace a neutral, immutable practice model.

Revision ID: 0021
Revises: 0016
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0021"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEMPLATE_ID = uuid.UUID("019a5e00-0000-7000-8000-000000000017")
MODEL_NAMESPACE = uuid.UUID("019a5e00-0000-7000-8000-000000000018")
PRACTICE_SITE_NAME = "Practice site (simulated)"
OLD_SITE_NAME = "Sample hostel (simulated)"


def _neutral_spec(spec: dict[str, object]) -> dict[str, object]:
    result = copy.deepcopy(spec)
    result["title"] = PRACTICE_SITE_NAME
    probes = result.get("probes")
    if isinstance(probes, list):
        for probe in probes:
            if not isinstance(probe, dict) or probe.get("id") != "internet_works":
                continue
            probe["label"] = "Internet access on a phone"
            probe["templates"] = {
                "en": "On your phone, does a normal website open? Please say yes or no.",
                "hi": "क्या आपके फ़ोन पर कोई सामान्य वेबसाइट खुलती है? हाँ या नहीं बताइए।",
                "hi-en": "Aapke phone par koi normal website khul rahi hai? Haan ya nahi batayiye.",
                "mr": "तुमच्या फोनवर एखादी साधी वेबसाइट उघडते का? हो किंवा नाही सांगा.",
            }
    return result


def _digest(spec: dict[str, object]) -> bytes:
    canonical = json.dumps(
        spec, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(canonical).digest()


def upgrade() -> None:
    connection = op.get_bind()
    source = (
        connection.execute(
            sa.text(
                "select spec from model_templates where purpose = 'sandbox' "
                "order by version desc limit 1"
            )
        )
        .mappings()
        .one()
    )
    spec = _neutral_spec(source["spec"])
    digest = _digest(spec)

    templates = sa.table(
        "model_templates",
        sa.column("id", pg.UUID(as_uuid=True)),
        sa.column("name", sa.String()),
        sa.column("kind", sa.String()),
        sa.column("purpose", sa.String()),
        sa.column("version", sa.Integer()),
        sa.column("spec", pg.JSONB()),
        sa.column("spec_sha256", sa.LargeBinary()),
    )
    connection.execute(
        templates.insert().values(
            id=TEMPLATE_ID,
            name=PRACTICE_SITE_NAME,
            kind="hostel",
            purpose="sandbox",
            version=2,
            spec=spec,
            spec_sha256=digest,
        )
    )

    sites = (
        connection.execute(
            sa.text("select id, org_id from sites where mode = 'sandbox' and archived_at is null")
        )
        .mappings()
        .all()
    )
    models = sa.table(
        "site_models",
        sa.column("id", pg.UUID(as_uuid=True)),
        sa.column("org_id", pg.UUID(as_uuid=True)),
        sa.column("site_id", pg.UUID(as_uuid=True)),
        sa.column("version", sa.Integer()),
        sa.column("status", sa.String()),
        sa.column("spec", pg.JSONB()),
        sa.column("spec_sha256", sa.LargeBinary()),
        sa.column("published_at", sa.DateTime(timezone=True)),
    )
    for site in sites:
        site_id = site["id"]
        org_id = site["org_id"]
        connection.execute(
            sa.text("select set_config('app.org_id', :org_id, true)"),
            {"org_id": str(org_id)},
        )
        latest = connection.execute(
            sa.text(
                "select coalesce(max(version), 0) from site_models "
                "where org_id = :org_id and site_id = :site_id"
            ),
            {"org_id": org_id, "site_id": site_id},
        ).scalar_one()
        model_id = uuid.uuid5(MODEL_NAMESPACE, f"{org_id}:{site_id}:sandbox-v2")
        connection.execute(
            models.insert().values(
                id=model_id,
                org_id=org_id,
                site_id=site_id,
                version=latest + 1,
                status="published",
                spec=spec,
                spec_sha256=digest,
                published_at=sa.func.now(),
            )
        )
        connection.execute(
            sa.text(
                "update sites set current_model_id = :model_id, name = :site_name "
                "where org_id = :org_id and id = :site_id and mode = 'sandbox'"
            ),
            {
                "model_id": model_id,
                "site_name": PRACTICE_SITE_NAME,
                "org_id": org_id,
                "site_id": site_id,
            },
        )
    connection.execute(sa.text("select set_config('app.org_id', '', true)"))


def downgrade() -> None:
    connection = op.get_bind()
    sites = (
        connection.execute(
            sa.text("select id, org_id from sites where mode = 'sandbox' and name = :site_name"),
            {"site_name": PRACTICE_SITE_NAME},
        )
        .mappings()
        .all()
    )
    for site in sites:
        connection.execute(
            sa.text("select set_config('app.org_id', :org_id, true)"),
            {"org_id": str(site["org_id"])},
        )
        model_id = uuid.uuid5(MODEL_NAMESPACE, f"{site['org_id']}:{site['id']}:sandbox-v2")
        connection.execute(
            sa.text(
                "update sites set current_model_id = ("
                "select id from site_models where org_id = :org_id and site_id = :site_id "
                "and id <> :model_id order by version desc limit 1), name = :old_name "
                "where org_id = :org_id and id = :site_id and current_model_id = :model_id"
            ),
            {
                "org_id": site["org_id"],
                "site_id": site["id"],
                "model_id": model_id,
                "old_name": OLD_SITE_NAME,
            },
        )
    connection.execute(sa.text("select set_config('app.org_id', '', true)"))
    op.execute("alter table site_models disable trigger site_models_immutable")
    for site in sites:
        model_id = uuid.uuid5(MODEL_NAMESPACE, f"{site['org_id']}:{site['id']}:sandbox-v2")
        connection.execute(
            sa.text("delete from site_models where id = :model_id"), {"model_id": model_id}
        )
    op.execute("alter table site_models enable trigger site_models_immutable")
    op.execute("delete from model_templates where id = '019a5e00-0000-7000-8000-000000000017'")
