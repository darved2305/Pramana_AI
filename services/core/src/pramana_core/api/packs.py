# No ``from __future__ import annotations``: FastAPI resolves dependency annotations at runtime.
"""Documented site information (``/v1/packs``). Contains no simulator state."""

from typing import Any

from fastapi import APIRouter, Request

from pramana_contracts import PackSummary

from ..directory import ConsoleQueries
from ..investigations import InvestigationService

router = APIRouter(prefix="/v1/packs", tags=["packs"])


@router.get("")
async def list_packs(request: Request) -> list[PackSummary]:
    """Every valid pack in ``packs/``. Public: packs hold documented layout, no secrets."""
    q: ConsoleQueries = request.app.state.console
    return q.list_packs()


@router.get("/{pack_id}")
async def get_pack(pack_id: str, request: Request) -> dict[str, Any]:
    svc: InvestigationService = request.app.state.investigations
    pack = svc.pack(pack_id)
    return {
        "id": pack.pack,
        "version": pack.version,
        "title": pack.title,
        "locations": [
            {
                "id": loc.id,
                "floor": loc.floor,
                "kind": loc.kind,
                "label": loc.label.en,
                "restricted": loc.restricted,
                "access_roles": [str(r) for r in loc.access_roles],
            }
            for loc in pack.locations
        ],
        "probes": [
            {
                "id": p.id,
                "label": p.label,
                "outcomes": p.outcomes,
                "roles": p.roles,
                "locations": [b.at for b in p.observes],
            }
            for p in pack.probes
        ],
        "decision_classes": [{"id": d.id, "label": d.label} for d in pack.decision_classes],
        "walking_roles": [str(r) for r in pack.walking_roles],
        "roles": [
            {"id": r.id, "label": r.label, "skill": r.skill} for r in pack.role_catalogue.values()
        ],
    }
