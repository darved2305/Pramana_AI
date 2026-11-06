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
import json
import os
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import Annotated
from typing import TypeVar

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from pramana_contracts import (
    ActRequest,
    ActResult,
    CreateScenario,
    FaultSpec,
    MoveRequest,
    MoveResult,
    ObserveRequest,
    ObserveResult,
    ParticipantView,
    PresenceCheck,
    PresenceCheckResult,
    RevealResult,
    ScenarioCreated,
)
from pramana_contracts.tokens import (
    TokenError,
    public_key_from_b64,
    verify,
    verify_capability,
)
from pramana_domain import DomainPack, load_pack

from .scenario import Scenario, ScenarioError, draw_fault

_Result = TypeVar("_Result")


class SimSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIM_", env_file=".env", extra="ignore")

    operator_key: SecretStr
    oracle_key: SecretStr | None = None
    participant_public_key: str
    cors_origins: list[str] = ["http://localhost:3000"]
    max_scenarios: int = 500
    state_file: str | None = None


class ScenarioStore:
    """Bounded scenarios with optional atomic snapshots for staging restarts."""

    def __init__(self, limit: int, state_file: str | None = None) -> None:
        self._items: OrderedDict[str, Scenario] = OrderedDict()
        self._limit = limit
        self._packs: dict[str, DomainPack] = {}
        self._state_file = Path(state_file) if state_file else None
        self._load()

    def pack(self, pack_id: str) -> DomainPack:
        if pack_id not in self._packs:
            try:
                self._packs[pack_id] = load_pack(pack_id)
            except (FileNotFoundError, ValueError) as exc:
                raise ScenarioError(422, "UNKNOWN_PACK", f"unknown pack {pack_id}") from exc
        return self._packs[pack_id]

    def add(self, scenario: Scenario) -> None:
        previous = self._items.copy()
        self._items[scenario.id] = scenario
        while len(self._items) > self._limit:
            self._items.popitem(last=False)
        try:
            self.persist()
        except Exception:
            self._items = previous
            raise

    def get(self, sid: str) -> Scenario:
        scenario = self._items.get(sid)
        if scenario is None:
            raise ScenarioError(404, "SCENARIO_NOT_FOUND", "scenario not found")
        return scenario

    def mutate(self, sid: str, update: Callable[[Scenario], _Result]) -> _Result:
        scenario = self.get(sid)
        if self._state_file is None:
            return update(scenario)

        snapshot = scenario.to_snapshot()
        try:
            result = update(scenario)
            self.persist()
            return result
        except Exception:
            self._items[sid] = Scenario.from_snapshot(self.pack(str(snapshot["pack_id"])), snapshot)
            raise

    def persist(self) -> None:
        if self._state_file is None:
            return
        path = self._state_file
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            payload = {
                "version": 2,
                "scenarios": [scenario.to_snapshot() for scenario in self._items.values()],
            }
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    def _load(self) -> None:
        path = self._state_file
        if path is None or not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            version = payload.get("version") if isinstance(payload, dict) else None
            if type(version) is not int or version not in (1, 2):
                raise ValueError("unsupported snapshot version")
            snapshots = payload.get("scenarios")
            if not isinstance(snapshots, list):
                raise ValueError("scenario list is invalid")
            for snapshot in snapshots:
                if not isinstance(snapshot, dict):
                    raise ValueError("scenario entry is invalid")
                if version == 2 and (
                    "presence_values" not in snapshot or "presence_attempts" not in snapshot
                ):
                    raise ValueError("presence state is missing")
                pack_id = snapshot.get("pack_id")
                if not isinstance(pack_id, str):
                    raise ValueError("scenario pack is invalid")
                scenario = Scenario.from_snapshot(self.pack(pack_id), snapshot)
                self._items[scenario.id] = scenario
            while len(self._items) > self._limit:
                self._items.popitem(last=False)
        except (OSError, TypeError, ValueError, KeyError) as exc:
            raise RuntimeError("simulator state file could not be loaded") from exc


def create_app(settings: SimSettings | None = None) -> FastAPI:
    cfg = settings or SimSettings()
    public_key = public_key_from_b64(cfg.participant_public_key)
    store = ScenarioStore(cfg.max_scenarios, cfg.state_file)
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
        return store.mutate(sid, lambda scenario: scenario.move(who, req.to))

    @app.post("/sim/v1/scenarios/{sid}/observe")
    async def observe(
        sid: str, req: ObserveRequest, who: Annotated[str, Depends(participant)]
    ) -> ObserveResult:
        return store.get(sid).observe(who, req.probe_id)

    @app.post("/sim/v1/scenarios/{sid}/act")
    async def act(
        sid: str, req: ActRequest, who: Annotated[str, Depends(participant)]
    ) -> ActResult:
        try:
            claims = verify_capability(public_key, req.capability)
        except TokenError as exc:
            raise HTTPException(403, str(exc)) from exc
        return store.mutate(
            sid, lambda scenario: scenario.act(who, req.action, req.target, claims)
        )

    @app.post("/sim/v1/scenarios/{sid}/presence/check", dependencies=[require_operator])
    async def check_presence(sid: str, req: PresenceCheck) -> PresenceCheckResult:
        return store.mutate(
            sid,
            lambda scenario: scenario.check_presence(
                req.participant_id, req.token_id, req.answer
            ),
        )

    @app.post("/sim/v1/scenarios/{sid}/close", status_code=204, dependencies=[require_operator])
    async def close(sid: str) -> None:
        store.mutate(sid, lambda scenario: scenario.close())

    @app.post("/sim/v1/scenarios/{sid}/reveal", dependencies=[require_operator])
    async def reveal(sid: str) -> RevealResult:
        return store.get(sid).reveal()

    @app.get("/sim/v1/scenarios/{sid}/truth", dependencies=[Depends(oracle)])
    async def truth(sid: str) -> FaultSpec:
        return store.get(sid).fault_spec

    return app
