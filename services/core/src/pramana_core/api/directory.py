# No ``from __future__ import annotations``: FastAPI resolves dependency annotations at runtime.
"""The participant directory (``/v1/participants``): people a site can call on."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from pramana_contracts import DirectoryParticipant, ParticipantPatch, ParticipantSpec, StaffRole

from ..auth.deps import require_staff
from ..directory import ConsoleQueries
from ..investigations import InvestigationService

router = APIRouter(prefix="/v1/participants", tags=["directory"])

ID = r"^[A-Za-z0-9_.:-]{1,64}$"
PackQ = Annotated[str, Query(pattern=ID)]
Pid = Annotated[str, Path(pattern=ID)]
Staff = Depends(require_staff())
Operator = Depends(require_staff(StaffRole.OPERATOR))


def _q(request: Request) -> ConsoleQueries:
    q: ConsoleQueries = request.app.state.console
    return q


def _svc(request: Request) -> InvestigationService:
    svc: InvestigationService = request.app.state.investigations
    return svc


@router.get("", dependencies=[Staff])
async def list_participants(
    request: Request, pack_id: Annotated[str | None, Query(pattern=ID)] = None
) -> list[DirectoryParticipant]:
    return await _q(request).list_participants(pack_id)


@router.post("", status_code=201, dependencies=[Operator])
async def add_participant(
    request: Request, body: ParticipantSpec, pack_id: PackQ = "campus_block_c"
) -> DirectoryParticipant:
    """Add a person. ``409 PARTICIPANT_EXISTS`` when the id is taken for this pack."""
    return await _q(request).add_participant(_svc(request).pack(pack_id), body)


@router.get("/{participant_id}", dependencies=[Staff])
async def get_participant(
    request: Request, participant_id: Pid, pack_id: PackQ = "campus_block_c"
) -> DirectoryParticipant:
    return await _q(request).get_participant(pack_id, participant_id)


@router.patch("/{participant_id}", dependencies=[Operator])
async def update_participant(
    request: Request, participant_id: Pid, body: ParticipantPatch, pack_id: PackQ = "campus_block_c"
) -> DirectoryParticipant:
    return await _q(request).update_participant(_svc(request).pack(pack_id), participant_id, body)


@router.delete("/{participant_id}", status_code=204, dependencies=[Operator])
async def delete_participant(
    request: Request, participant_id: Pid, pack_id: PackQ = "campus_block_c"
) -> None:
    """Remove a person from the directory. Past investigations keep their own copy."""
    await _q(request).delete_participant(pack_id, participant_id)
