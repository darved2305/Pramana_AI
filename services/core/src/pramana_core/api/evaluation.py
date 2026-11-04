# No ``from __future__ import annotations``: FastAPI resolves dependency annotations at runtime.
"""Benchmark reports (``/v1/evaluation``): the harness's own ``summary.json`` files, served as
written. Nothing is computed here."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request

from pramana_contracts import EvaluationReport, EvaluationReportSummary

from ..auth.deps import require_staff
from ..directory import ConsoleQueries

router = APIRouter(
    prefix="/v1/evaluation", tags=["evaluation"], dependencies=[Depends(require_staff())]
)


def _q(request: Request) -> ConsoleQueries:
    q: ConsoleQueries = request.app.state.console
    return q


@router.get("/reports")
async def list_reports(request: Request) -> list[EvaluationReportSummary]:
    """Runs found under ``eval/reports/*/summary.json`` (``EVAL_REPORTS_DIR``), newest first."""
    return _q(request).list_reports()


@router.get("/reports/{run_id}")
async def get_report(
    request: Request, run_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_.-]{1,128}$")]
) -> EvaluationReport:
    return _q(request).get_report(run_id)
