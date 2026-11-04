"""Simulator HTTP service (``/sim/v1``).

Access model:

* operator key (held by the core): create, close and reveal scenarios. Reveal is refused until
  the scenario is closed, and a closed scenario answers no further observations, so revealing
  truth early ends the investigation's access to the world.
* participant token (minted by the core, verified here with its public key only): view, move,
  observe, scoped to one participant in one scenario.
* oracle key (evaluation harness only, never configured in the core): read truth of an open
  scenario. When unset, the route is disabled.
"""

# No ``from __future__ import annotations``: FastAPI must resolve the closure dependencies
# referenced in ``Annotated[..., Depends(...)]`` at definition time.

import hmac
from collections import OrderedDict
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from pramana_contracts import (
    CreateScenario,
    FaultSpec,
    MoveRequest,
    MoveResult,
    ObserveRequest,
    ObserveResult,
    ParticipantView,
    RevealResult,
    ScenarioCreated,
)
from pramana_contracts.tokens import TokenError, public_key_from_b64, verify
from pramana_domain import DomainPack, load_pack

from .scenario import Scenario, ScenarioError, draw_fault


class SimSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIM_", env_file=".env", extra="ignore")

    operator_key: SecretStr
    oracle_key: SecretStr | None = None
    participant_public_key: str
    cors_origins: list[str] = ["http://localhost:3000"]
    max_scenarios: int = 500


class ScenarioStore:
    """In-memory scenarios, bounded: the oldest are evicted first."""

    def __init__(self, limit: int) -> None:
        self._items: OrderedDict[str, Scenario] = OrderedDict()
        self._limit = limit
        self._packs: dict[str, DomainPack] = {}

    def pack(self, pack_id: str) -> DomainPack:
        if pack_id not in self._packs:
            try:
                self._packs[pack_id] = load_pack(pack_id)
            except (FileNotFoundError, ValueError) as exc:
                raise ScenarioError(422, "UNKNOWN_PACK", f"unknown pack {pack_id}") from exc
        return self._packs[pack_id]

    def add(self, scenario: Scenario) -> None:
        self._items[scenario.id] = scenario
        while len(self._items) > self._limit:
            self._items.popitem(last=False)

    def get(self, sid: str) -> Scenario:
        scenario = self._items.get(sid)
        if scenario is None:
            raise ScenarioError(404, "SCENARIO_NOT_FOUND", "scenario not found")
        return scenario


def create_app(settings: SimSettings | None = None) -> FastAPI:
    cfg = settings or SimSettings()
    public_key = public_key_from_b64(cfg.participant_public_key)
    store = ScenarioStore(cfg.max_scenarios)
    app = FastAPI(title="Pramana simulator", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(ScenarioError)
    async def _scenario_error(_: Request, exc: ScenarioError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status
        )

    def operator(x_operator_key: Annotated[str | None, Header()] = None) -> None:
        if x_operator_key is None or not hmac.compare_digest(
            x_operator_key.encode(), cfg.operator_key.get_secret_value().encode()
        ):
            raise HTTPException(401, "operator key required")

    def oracle(x_oracle_key: Annotated[str | None, Header()] = None) -> None:
        if cfg.oracle_key is None:
            raise HTTPException(404, "not found")
        if x_oracle_key is None or not hmac.compare_digest(
            x_oracle_key.encode(), cfg.oracle_key.get_secret_value().encode()
        ):
            raise HTTPException(403, "oracle key required")

    def participant(sid: str, authorization: Annotated[str | None, Header()] = None) -> str:
        if authorization is None or not authorization.startswith("Bearer "):
            raise HTTPException(401, "participant token required")
        try:
            claims = verify(public_key, authorization.removeprefix("Bearer ").strip())
        except TokenError as exc:
            raise HTTPException(401, str(exc)) from exc
        if claims.scn != sid:
            raise HTTPException(403, "token is for another scenario")
        return claims.sub

    require_operator = Depends(operator)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/sim/v1/scenarios", status_code=201, dependencies=[require_operator])
    async def create(req: CreateScenario) -> ScenarioCreated:
        pack = store.pack(req.pack_id)
        fault = draw_fault(pack, req.seed) if req.fault == "random" else req.fault
        assert isinstance(fault, FaultSpec)
        scenario = Scenario.create(pack, fault, req.participants)
        store.add(scenario)
        return ScenarioCreated(scenario_id=scenario.id, commitment=scenario.commitment)

    @app.get("/sim/v1/scenarios/{sid}/view")
    async def view(sid: str, who: Annotated[str, Depends(participant)]) -> ParticipantView:
        return store.get(sid).view(who)

    @app.post("/sim/v1/scenarios/{sid}/move")
    async def move(
        sid: str, req: MoveRequest, who: Annotated[str, Depends(participant)]
    ) -> MoveResult:
        return store.get(sid).move(who, req.to)

    @app.post("/sim/v1/scenarios/{sid}/observe")
    async def observe(
        sid: str, req: ObserveRequest, who: Annotated[str, Depends(participant)]
    ) -> ObserveResult:
        return store.get(sid).observe(who, req.probe_id)

    @app.post("/sim/v1/scenarios/{sid}/close", status_code=204, dependencies=[require_operator])
    async def close(sid: str) -> None:
        store.get(sid).close()

    @app.post("/sim/v1/scenarios/{sid}/reveal", dependencies=[require_operator])
    async def reveal(sid: str) -> RevealResult:
        return store.get(sid).reveal()

    @app.get("/sim/v1/scenarios/{sid}/truth", dependencies=[Depends(oracle)])
    async def truth(sid: str) -> FaultSpec:
        return store.get(sid).fault_spec

    return app
