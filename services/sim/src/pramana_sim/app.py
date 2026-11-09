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

import contextlib
import hmac
import json
import os
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Annotated, Literal, Self, TypeVar, cast

import asyncpg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from pramana_contracts import (
    ActRequest,
    ActResult,
    CreateScenario,
    DocumentedModel,
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
from pramana_domain.spec_storage import load_spec, spec_digest

from .scenario import Scenario, ScenarioError, draw_fault

_Result = TypeVar("_Result")


class SimSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SIM_", env_file=".env", extra="ignore", populate_by_name=True
    )

    mode: Literal["dev", "test", "demo", "production"] = Field(
        default="dev", validation_alias="PRAMANA_MODE"
    )
    local_production_test: bool = Field(
        default=False, validation_alias="PRAMANA_LOCAL_PRODUCTION_TEST"
    )
    operator_key: SecretStr
    oracle_key: SecretStr | None = None
    participant_public_key: str
    cors_origins: list[str] = ["http://localhost:3000"]
    max_scenarios: int = 500
    state_file: str | None = None
    database_url: str | None = None
    database_pool_size: int = Field(default=1, ge=1, le=4)
    require_documented_models: bool = True

    @model_validator(mode="after")
    def _production_state_is_durable(self) -> Self:
        if self.mode == "production":
            if not self.database_url:
                raise ValueError("production requires SIM_DATABASE_URL")
            if self.state_file:
                raise ValueError("production simulator state must use PostgreSQL")
            if self.oracle_key is not None:
                raise ValueError("the simulator oracle key is forbidden in production")
            url = make_url(self.database_url)
            if (
                not url.drivername.startswith("postgresql")
                or not url.host
                or (
                    self.local_production_test
                    and url.host.lower() not in {"host.docker.internal", "localhost", "postgres"}
                )
                or (
                    url.host.lower() in {"localhost", "127.0.0.1", "::1"}
                    and not self.local_production_test
                )
            ):
                raise ValueError(
                    "production requires an explicit remote PostgreSQL SIM_DATABASE_URL"
                )
        return self


class ScenarioStore:
    """In-memory scenarios with optional atomic snapshots for local restart checks."""

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

    @staticmethod
    def documented(pack_id: str, model: DocumentedModel) -> DomainPack:
        try:
            if spec_digest(model.spec).hex() != model.sha256:
                raise ValueError("documented model hash mismatch")
            pack = load_spec(model.spec)
            if pack.pack != pack_id:
                raise ValueError("documented model label mismatch")
            return pack
        except ValueError as exc:
            raise ScenarioError(422, "INVALID_MODEL", "the documented model is invalid") from exc

    def restore(self, snapshot: dict[str, object], *, legacy: bool = False) -> Scenario:
        pack_id = snapshot.get("pack_id")
        if not isinstance(pack_id, str):
            raise ValueError("scenario pack is invalid")
        raw_model = snapshot.get("documented_model")
        if raw_model is None:
            if not legacy:
                raise ValueError("documented model is missing")
            pack = self.pack(pack_id)
        else:
            pack = self.documented(pack_id, DocumentedModel.model_validate(raw_model))
        return Scenario.from_snapshot(pack, snapshot)

    async def add(self, scenario: Scenario) -> None:
        previous = self._items.copy()
        self._items[scenario.id] = scenario
        while len(self._items) > self._limit:
            self._items.popitem(last=False)
        try:
            self.persist()
        except Exception:
            self._items = previous
            raise

    async def get(self, sid: str) -> Scenario:
        scenario = self._items.get(sid)
        if scenario is None:
            raise ScenarioError(404, "SCENARIO_NOT_FOUND", "scenario not found")
        return scenario

    async def mutate(self, sid: str, update: Callable[[Scenario], _Result]) -> _Result:
        scenario = await self.get(sid)
        if self._state_file is None:
            return update(scenario)

        snapshot = scenario.to_snapshot()
        try:
            result = update(scenario)
            self.persist()
            return result
        except Exception:
            self._items[sid] = self.restore(snapshot)
            raise

    async def ping(self) -> None:
        return None

    def persist(self) -> None:
        if self._state_file is None:
            return
        path = self._state_file
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        try:
            payload = {
                "version": 3,
                "scenarios": [scenario.to_snapshot() for scenario in self._items.values()],
            }
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()

    def _load(self) -> None:
        path = self._state_file
        if path is None or not path.is_file():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            version = payload.get("version") if isinstance(payload, dict) else None
            if type(version) is not int or version not in (1, 2, 3):
                raise ValueError("unsupported snapshot version")
            snapshots = payload.get("scenarios")
            if not isinstance(snapshots, list):
                raise ValueError("scenario list is invalid")
            for snapshot in snapshots:
                if not isinstance(snapshot, dict):
                    raise ValueError("scenario entry is invalid")
                if version in (2, 3) and (
                    "presence_values" not in snapshot or "presence_attempts" not in snapshot
                ):
                    raise ValueError("presence state is missing")
                scenario = self.restore(snapshot, legacy=version in (1, 2))
                self._items[scenario.id] = scenario
            while len(self._items) > self._limit:
                self._items.popitem(last=False)
        except (OSError, TypeError, ValueError, KeyError, ScenarioError) as exc:
            raise RuntimeError("simulator state file could not be loaded") from exc


class PostgresScenarioStore:
    """PostgreSQL-backed snapshots, serialized with row locks across Cloud Run instances."""

    def __init__(self, pool: asyncpg.Pool, limit: int) -> None:
        self._pool = pool
        self._limit = limit
        self._codec = ScenarioStore(limit)

    def pack(self, pack_id: str) -> DomainPack:
        return self._codec.pack(pack_id)

    @staticmethod
    def documented(pack_id: str, model: DocumentedModel) -> DomainPack:
        return ScenarioStore.documented(pack_id, model)

    @classmethod
    async def connect(cls, database_url: str, limit: int, pool_size: int) -> Self:
        url = make_url(database_url)
        if not url.drivername.startswith("postgresql"):
            raise ValueError("SIM_DATABASE_URL must use PostgreSQL")
        params: dict[str, object] = {
            "host": url.host,
            "port": url.port or 5432,
            "user": url.username,
            "password": url.password,
            "database": url.database,
            "min_size": 1,
            "max_size": pool_size,
            "command_timeout": 10,
            "server_settings": {"search_path": "pramana_sim"},
        }
        # The same libpq-style modes the core's asyncpg URL takes ("require", "verify-full").
        sslmode = url.query.get("sslmode") or url.query.get("ssl")
        if isinstance(sslmode, str) and sslmode != "disable":
            params["ssl"] = sslmode
        pool = await asyncpg.create_pool(**params)
        return cls(pool, limit)

    async def add(self, scenario: Scenario) -> None:
        payload = json.dumps(scenario.to_snapshot(), ensure_ascii=False, separators=(",", ":"))
        async with self._pool.acquire() as connection, connection.transaction():
            await connection.execute(
                "select pg_advisory_xact_lock(hashtext('pramana_sim.scenario_capacity'))"
            )
            # Like the in-memory store, stay bounded by forgetting the stalest worlds, closed ones
            # first, so a small free database never fills up with finished practice runs.
            await connection.execute(
                "delete from scenarios where id in (select id from scenarios "
                "order by (status = 'closed') desc, updated_at asc "
                "limit greatest((select count(*) from scenarios) - $1 + 1, 0))",
                self._limit,
            )
            await connection.execute(
                "insert into scenarios (id, snapshot, status) values ($1, $2::jsonb, $3)",
                scenario.id,
                payload,
                scenario.status.value,
            )

    async def get(self, sid: str) -> Scenario:
        async with self._pool.acquire() as connection:
            snapshot = await connection.fetchval(
                "select snapshot from scenarios where id = $1", sid
            )
        if snapshot is None:
            raise ScenarioError(404, "SCENARIO_NOT_FOUND", "scenario not found")
        return self._restore(snapshot)

    async def mutate(self, sid: str, update: Callable[[Scenario], _Result]) -> _Result:
        async with self._pool.acquire() as connection, connection.transaction():
            snapshot = await connection.fetchval(
                "select snapshot from scenarios where id = $1 for update", sid
            )
            if snapshot is None:
                raise ScenarioError(404, "SCENARIO_NOT_FOUND", "scenario not found")
            scenario = self._restore(snapshot)
            result = update(scenario)
            payload = json.dumps(scenario.to_snapshot(), ensure_ascii=False, separators=(",", ":"))
            await connection.execute(
                "update scenarios set snapshot = $2::jsonb, status = $3, updated_at = now() "
                "where id = $1",
                sid,
                payload,
                scenario.status.value,
            )
            return result

    async def ping(self) -> None:
        async with self._pool.acquire() as connection:
            await connection.fetchval("select 1")

    def _restore(self, value: object) -> Scenario:
        """Every read re-validates the stored world, including its sealed-truth commitment."""
        snapshot = json.loads(value) if isinstance(value, str) else value
        try:
            if not isinstance(snapshot, dict):
                raise ValueError("stored scenario is invalid")
            return self._codec.restore(snapshot)
        except (TypeError, ValueError, KeyError) as exc:
            raise RuntimeError("stored simulator scenario could not be loaded") from exc

    async def close(self) -> None:
        await self._pool.close()


def create_app(settings: SimSettings | None = None) -> FastAPI:
    cfg = settings or SimSettings()
    public_key = public_key_from_b64(cfg.participant_public_key)
    memory_store = (
        ScenarioStore(cfg.max_scenarios, cfg.state_file) if not cfg.database_url else None
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if cfg.database_url:
            store: ScenarioStore | PostgresScenarioStore = await PostgresScenarioStore.connect(
                cfg.database_url, cfg.max_scenarios, cfg.database_pool_size
            )
        else:
            assert memory_store is not None
            store = memory_store
        app.state.store = store
        try:
            yield
        finally:
            if isinstance(store, PostgresScenarioStore):
                await store.close()

    app = FastAPI(title="Pramana simulator", version="0.1.0", lifespan=lifespan)
    app.state.store = memory_store

    def store_for(request: Request) -> ScenarioStore | PostgresScenarioStore:
        return cast(ScenarioStore | PostgresScenarioStore, request.app.state.store)

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

    @app.get("/ready")
    async def ready(request: Request) -> JSONResponse:
        try:
            await store_for(request).ping()
        except Exception as exc:
            return JSONResponse(
                {"status": "not_ready", "database": type(exc).__name__}, status_code=503
            )
        return JSONResponse({"status": "ready", "database": "ok"})

    @app.post("/sim/v1/scenarios", status_code=201, dependencies=[require_operator])
    async def create(req: CreateScenario, request: Request) -> ScenarioCreated:
        if req.documented_model is None:
            if cfg.require_documented_models:
                raise ScenarioError(422, "MODEL_REQUIRED", "supply a documented site model")
            pack = store_for(request).pack(req.pack_id)
        else:
            pack = store_for(request).documented(req.pack_id, req.documented_model)
        fault = draw_fault(pack, req.seed) if req.fault == "random" else req.fault
        assert isinstance(fault, FaultSpec)
        scenario = Scenario.create(
            pack, fault, req.participants, documented_model=req.documented_model
        )
        await store_for(request).add(scenario)
        return ScenarioCreated(scenario_id=scenario.id, commitment=scenario.commitment)

    @app.get("/sim/v1/scenarios/{sid}/view")
    async def view(
        sid: str, request: Request, who: Annotated[str, Depends(participant)]
    ) -> ParticipantView:
        return (await store_for(request).get(sid)).view(who)

    @app.post("/sim/v1/scenarios/{sid}/move")
    async def move(
        sid: str, req: MoveRequest, request: Request, who: Annotated[str, Depends(participant)]
    ) -> MoveResult:
        return await store_for(request).mutate(sid, lambda scenario: scenario.move(who, req.to))

    @app.post("/sim/v1/scenarios/{sid}/observe")
    async def observe(
        sid: str, req: ObserveRequest, request: Request, who: Annotated[str, Depends(participant)]
    ) -> ObserveResult:
        return (await store_for(request).get(sid)).observe(who, req.probe_id)

    @app.post("/sim/v1/scenarios/{sid}/act")
    async def act(
        sid: str, req: ActRequest, request: Request, who: Annotated[str, Depends(participant)]
    ) -> ActResult:
        try:
            claims = verify_capability(public_key, req.capability)
        except TokenError as exc:
            raise HTTPException(403, str(exc)) from exc
        return await store_for(request).mutate(
            sid, lambda scenario: scenario.act(who, req.action, req.target, claims)
        )

    @app.post("/sim/v1/scenarios/{sid}/presence/check", dependencies=[require_operator])
    async def check_presence(sid: str, req: PresenceCheck, request: Request) -> PresenceCheckResult:
        return await store_for(request).mutate(
            sid,
            lambda scenario: scenario.check_presence(req.participant_id, req.token_id, req.answer),
        )

    @app.post("/sim/v1/scenarios/{sid}/close", status_code=204, dependencies=[require_operator])
    async def close(sid: str, request: Request) -> None:
        await store_for(request).mutate(sid, lambda scenario: scenario.close())

    @app.post("/sim/v1/scenarios/{sid}/reveal", dependencies=[require_operator])
    async def reveal(sid: str, request: Request) -> RevealResult:
        return (await store_for(request).get(sid)).reveal()

    @app.get("/sim/v1/scenarios/{sid}/truth", dependencies=[Depends(oracle)])
    async def truth(sid: str, request: Request) -> FaultSpec:
        return (await store_for(request).get(sid)).fault_spec

    return app
