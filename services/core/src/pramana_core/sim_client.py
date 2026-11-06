"""Operator-side client for the simulator.

The core holds only the operator key: it can create, close and reveal scenarios, and it can mint
participant tokens. It has no oracle key and no route to read hidden truth while a scenario is
open. Participants' browsers talk to the simulator directly with their own tokens.
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel

from pramana_contracts import (
    CreateScenario,
    PresenceVerificationResult,
    RevealResult,
    ScenarioCreated,
    VerifyPresenceRequest,
)

from .errors import ApiError


class SimClient:
    def __init__(
        self,
        base_url: str,
        operator_key: str,
        timeout_s: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-Operator-Key": operator_key},
            timeout=httpx.Timeout(timeout_s),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post(self, path: str, body: BaseModel | None = None) -> httpx.Response:
        try:
            resp = await self._http.post(
                path,
                content=body.model_dump_json() if body else None,
                headers={"content-type": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise ApiError(
                503, "SIM_UNAVAILABLE", f"simulator unreachable: {type(exc).__name__}"
            ) from exc
        if resp.status_code >= 500:
            raise ApiError(503, "SIM_UNAVAILABLE", "simulator error")
        if resp.status_code >= 400:
            raise ApiError(502, "SIM_REJECTED", f"simulator rejected request: {resp.text[:200]}")
        return resp

    async def create_scenario(self, req: CreateScenario) -> ScenarioCreated:
        resp = await self._post("/sim/v1/scenarios", req)
        return ScenarioCreated.model_validate_json(resp.content)

    async def close(self, scenario_id: str) -> None:
        await self._post(f"/sim/v1/scenarios/{scenario_id}/close")

    async def reveal(self, scenario_id: str) -> RevealResult:
        resp = await self._post(f"/sim/v1/scenarios/{scenario_id}/reveal")
        return RevealResult.model_validate_json(resp.content)

    async def verify_presence(
        self, scenario_id: str, participant_id: str, token_id: str, answer: str
    ) -> PresenceVerificationResult:
        req = VerifyPresenceRequest(participant_id=participant_id, token_id=token_id, answer=answer)
        resp = await self._post(f"/sim/v1/scenarios/{scenario_id}/presence/verify", req)
        return PresenceVerificationResult.model_validate_json(resp.content)

    async def health(self) -> bool:
        try:
            resp = await self._http.get("/health")
        except httpx.HTTPError:
            return False
        return resp.status_code == 200
