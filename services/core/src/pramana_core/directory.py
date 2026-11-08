"""The participant directory and the investigation list: console read models.

Directory entries are plain records (no event log): they are reference data that an operator
edits, and an investigation copies the participants it needs into its own creation event, so
editing the directory never changes a past investigation.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from sqlalchemy import func, or_, select

from pramana_contracts import (
    DirectoryParticipant,
    EvaluationReport,
    EvaluationReportSummary,
    InvestigationPage,
    InvestigationStatus,
    InvestigationSummary,
    PackSummary,
    ParticipantPatch,
    ParticipantSpec,
)
from pramana_domain import DomainPack, load_pack
from pramana_domain.pack import default_packs_dir

from .db import Database, DirectoryParticipantRow, InvestigationRow, current_org
from .errors import ApiError, not_found

REPO_ROOT = Path(__file__).resolve().parents[4]


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _entry(row: DirectoryParticipantRow) -> DirectoryParticipant:
    return DirectoryParticipant(
        pack_id=row.pack_id,
        participant=ParticipantSpec.model_validate(row.spec),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@dataclass
class ConsoleQueries:
    db: Database
    packs_dir: Path
    reports_dir: Path

    # -- packs -------------------------------------------------------------------------------

    def list_packs(self) -> list[PackSummary]:
        out: list[PackSummary] = []
        for path in sorted(self.packs_dir.glob("*.yaml")):
            try:
                pack = load_pack(path)
            except (ValueError, OSError, yaml.YAMLError):
                continue  # an invalid pack is not offered (the validator test catches it)
            out.append(
                PackSummary(
                    id=pack.pack,
                    version=pack.version,
                    title=pack.title,
                    locations=len(pack.locations),
                    probes=len(pack.probes),
                )
            )
        return out

    # -- directory ---------------------------------------------------------------------------

    @staticmethod
    def _check_location(pack: DomainPack, spec: ParticipantSpec) -> None:
        if spec.location_id not in pack.location_by_id:
            raise ApiError(422, "UNKNOWN_LOCATION", f"unknown location {spec.location_id}")

    async def list_participants(self, pack_id: str | None) -> list[DirectoryParticipant]:
        stmt = select(DirectoryParticipantRow).order_by(
            DirectoryParticipantRow.pack_id, DirectoryParticipantRow.id
        )
        if pack_id is not None:
            stmt = stmt.where(DirectoryParticipantRow.pack_id == pack_id)
        async with self.db.read() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return [_entry(r) for r in rows]

    async def get_participant(self, pack_id: str, pid: str) -> DirectoryParticipant:
        async with self.db.read() as session:
            row = await session.get(DirectoryParticipantRow, (pack_id, pid))
        if row is None:
            raise not_found("participant")
        return _entry(row)

    async def add_participant(
        self, pack: DomainPack, spec: ParticipantSpec
    ) -> DirectoryParticipant:
        self._check_location(pack, spec)
        now = datetime.now(UTC)
        async with self.db.transaction() as session:
            if await session.get(DirectoryParticipantRow, (pack.pack, spec.id)) is not None:
                raise ApiError(409, "PARTICIPANT_EXISTS", f"{spec.id} is already in the directory")
            row = DirectoryParticipantRow(
                pack_id=pack.pack,
                id=spec.id,
                spec=spec.model_dump(mode="json"),
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        return _entry(row)

    async def update_participant(
        self, pack: DomainPack, pid: str, patch: ParticipantPatch
    ) -> DirectoryParticipant:
        async with self.db.transaction() as session:
            row = await session.get(DirectoryParticipantRow, (pack.pack, pid), with_for_update=True)
            if row is None:
                raise not_found("participant")
            merged = {**row.spec, **patch.model_dump(mode="json", exclude_unset=True)}
            try:
                spec = ParticipantSpec.model_validate(merged)
            except ValidationError as exc:
                raise ApiError(422, "INVALID_PARTICIPANT", str(exc.errors()[0]["msg"])) from exc
            self._check_location(pack, spec)
            row.spec = spec.model_dump(mode="json")
            row.updated_at = datetime.now(UTC)
        return _entry(row)

    async def delete_participant(self, pack_id: str, pid: str) -> None:
        async with self.db.transaction() as session:
            row = await session.get(DirectoryParticipantRow, (pack_id, pid), with_for_update=True)
            if row is None:
                raise not_found("participant")
            await session.delete(row)

    # -- investigation list ----------------------------------------------------------------

    async def list_investigations(
        self,
        *,
        statuses: list[InvestigationStatus],
        q: str | None,
        limit: int,
        offset: int,
    ) -> InvestigationPage:
        report_text = InvestigationRow.request["report"]["text"].astext
        conds: list[Any] = []
        if current_org.get() is not None:
            conds.append(InvestigationRow.org_id == current_org.get())
        if statuses:
            conds.append(InvestigationRow.status.in_([s.value for s in statuses]))
        if q:
            pattern = f"%{_like_escape(q.strip())}%"
            conds.append(
                or_(
                    report_text.ilike(pattern, escape="\\"),
                    InvestigationRow.id.ilike(pattern, escape="\\"),
                )
            )
        async with self.db.read() as session:
            total = (
                await session.execute(
                    select(func.count()).select_from(InvestigationRow).where(*conds)
                )
            ).scalar_one()
            rows = (
                (
                    await session.execute(
                        select(InvestigationRow)
                        .where(*conds)
                        .order_by(InvestigationRow.created_at.desc(), InvestigationRow.id.desc())
                        .limit(limit)
                        .offset(offset)
                    )
                )
                .scalars()
                .all()
            )
        items = [
            InvestigationSummary(
                id=r.id,
                pack_id=r.pack_id,
                status=InvestigationStatus(r.status),
                created_at=r.created_at,
                updated_at=r.updated_at,
                report_text=r.request["report"]["text"],
                reporter_id=r.request["report"]["reporter_id"],
                participant_count=len(r.request.get("participants", [])),
                decision_class=(r.outcome or {}).get("decision_class"),
                decision_probability=(r.outcome or {}).get("decision_probability"),
            )
            for r in rows
        ]
        return InvestigationPage(items=items, total=int(total), limit=limit, offset=offset)

    # -- evaluation reports --------------------------------------------------------------------

    def _report_path(self, run_id: str) -> Path:
        # run_id is validated by the route's pattern; resolve and confine it anyway.
        base = self.reports_dir.resolve()
        path = (base / run_id / "summary.json").resolve()
        if base not in path.parents:
            raise not_found("report")
        return path

    @staticmethod
    def _read_summary(path: Path) -> dict[str, Any]:
        def finite(x: Any) -> Any:
            if isinstance(x, float) and not math.isfinite(x):
                return None
            if isinstance(x, dict):
                return {k: finite(v) for k, v in x.items()}
            if isinstance(x, list):
                return [finite(v) for v in x]
            return x

        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("policies"), dict):
            raise ValueError("not a benchmark summary")
        out: dict[str, Any] = finite(data)
        return out

    def list_reports(self) -> list[EvaluationReportSummary]:
        if not self.reports_dir.is_dir():
            return []
        out: list[EvaluationReportSummary] = []
        for path in self.reports_dir.glob("*/summary.json"):
            try:
                data = self._read_summary(path)
            except (ValueError, OSError):
                continue
            seeds = data.get("seeds")
            out.append(
                EvaluationReportSummary(
                    run_id=path.parent.name,
                    git_sha=data.get("git_sha"),
                    seeds=[int(s) for s in seeds] if isinstance(seeds, list) else None,
                    policies=list(data["policies"]),
                    modified_at=datetime.fromtimestamp(path.stat().st_mtime, UTC),
                )
            )
        out.sort(key=lambda r: r.modified_at, reverse=True)
        return out

    def get_report(self, run_id: str) -> EvaluationReport:
        path = self._report_path(run_id)
        if not path.is_file():
            raise not_found("report")
        try:
            summary = self._read_summary(path)
        except (ValueError, OSError) as exc:
            raise ApiError(422, "INVALID_REPORT", f"{run_id}/summary.json is not readable") from exc
        return EvaluationReport(
            run_id=run_id,
            modified_at=datetime.fromtimestamp(path.stat().st_mtime, UTC),
            summary=summary,
        )


def make_queries(db: Database, reports_dir: str) -> ConsoleQueries:
    rd = Path(reports_dir)
    return ConsoleQueries(
        db=db, packs_dir=default_packs_dir(), reports_dir=rd if rd.is_absolute() else REPO_ROOT / rd
    )
