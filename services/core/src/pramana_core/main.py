# No ``from __future__ import annotations``: FastAPI resolves dependency annotations at runtime.
"""Core service application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from pramana_contracts import CONTRACTS_VERSION
from pramana_domain import load_pack

from .api import investigations as investigations_api
from .api import packs as packs_api
from .api import stream as stream_api
from .api import voice as voice_api
from .api import voice_turns as voice_turns_api
from .db import Database, make_engine
from .errors import install_error_handlers
from .investigations import InvestigationService
from .language.extraction import RuleExtractor
from .language.hybrid import HybridExtractor
from .llm import LlmClient
from .observability import RequestContextMiddleware, configure_logging, log
from .runtime.broadcast import EventBroadcaster
from .runtime.recovery import recover
from .settings import Settings, get_settings
from .sim_client import SimClient
from .voice.conversation import QuestionAudioCache
from .voice.gnani import GnaniClient
from .voice.governor import DbLedger, GovernorLimits, VoiceGovernor
from .voice.media import ActiveSessions


def _llm_extractor(cfg: Settings) -> LlmClient | None:
    """Interactive settings: short timeout and no waiting on quota, so a turn never blocks."""
    if cfg.llm_extractor_provider == "none":
        return None
    key = cfg.gemini_api_key if cfg.llm_extractor_provider == "gemini" else cfg.groq_api_key
    if key is None:
        log.warning("llm_extractor_disabled", reason="no API key")
        return None
    default = "gemini-3.1-flash-lite" if cfg.llm_extractor_provider == "gemini" else None
    return LlmClient(
        cfg.llm_extractor_provider,
        cfg.llm_extractor_model or default,
        cache_dir=Path(cfg.llm_cache_dir),
        api_key=key.get_secret_value(),
        timeout_s=8.0,
        max_wait_s=2.0,
        total_timeout_s=10.0,
    )


def create_app(
    settings: Settings | None = None,
    *,
    sim_transport: httpx.AsyncBaseTransport | None = None,
    gnani_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    cfg = settings or get_settings()
    configure_logging(cfg.log_level, cfg.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(make_engine(cfg))
        sim = SimClient(
            cfg.sim_url,
            cfg.sim_operator_key.get_secret_value(),
            cfg.sim_timeout_s,
            transport=sim_transport,
        )
        gnani = GnaniClient(
            api_key=cfg.gnani_api_key.get_secret_value() if cfg.gnani_api_key else None,
            base_url=cfg.gnani_base_url,
            timeout_s=cfg.gnani_timeout_s,
            governor=VoiceGovernor(
                GovernorLimits(
                    stt_rest_per_min=cfg.gnani_stt_rest_per_min,
                    tts_per_min=cfg.gnani_tts_per_min,
                    max_streams=cfg.gnani_max_streams,
                    rest_max_inflight=cfg.gnani_rest_max_inflight,
                    daily_budget_inr=cfg.voice_daily_budget_inr,
                    max_stream_s=cfg.voice_max_stream_s,
                ),
                DbLedger(db),
            ),
            transport=gnani_transport,
        )
        app.state.settings = cfg
        app.state.db = db
        app.state.sim = sim
        app.state.gnani = gnani
        app.state.question_audio = QuestionAudioCache()
        app.state.investigations = InvestigationService(
            db,
            sim,
            HybridExtractor(RuleExtractor(), _llm_extractor(cfg)),
            cfg.participant_signing_key.get_secret_value(),
            browser_sim_url=cfg.browser_sim_url,
        )
        broadcaster = EventBroadcaster()
        db.commit_listeners.append(broadcaster.publish)
        app.state.broadcaster = broadcaster
        app.state.media_sessions = ActiveSessions()
        app.state.recovery = (
            (await recover(app.state.investigations)).as_dict() if cfg.recover_on_startup else None
        )
        log.info("startup", mode=cfg.mode, gnani_configured=gnani.configured)
        try:
            yield
        finally:
            broadcaster.close()
            await gnani.aclose()
            await sim.aclose()
            await db.dispose()
            log.info("shutdown")

    app = FastAPI(title="Pramana core", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    install_error_handlers(app)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness: the process is up. Does not touch dependencies."""
        return {"status": "ok", "contracts": CONTRACTS_VERSION}

    @app.get("/ready")
    async def ready(request: Request) -> JSONResponse:
        """Readiness: database and simulator reachable, packs loadable."""
        checks: dict[str, str] = {}
        try:
            await request.app.state.db.ping()
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {type(exc).__name__}"
        checks["simulator"] = "ok" if await request.app.state.sim.health() else "unreachable"
        try:
            load_pack("campus_block_c")
            checks["packs"] = "ok"
        except Exception as exc:
            checks["packs"] = f"error: {type(exc).__name__}"
        checks["gnani"] = "configured" if request.app.state.gnani.configured else "not configured"
        ok = all(v == "ok" for k, v in checks.items() if k != "gnani")
        return JSONResponse(
            {"status": "ready" if ok else "not_ready", "checks": checks},
            status_code=200 if ok else 503,
        )

    app.include_router(investigations_api.router)
    app.include_router(stream_api.router)
    app.include_router(packs_api.router)
    app.include_router(voice_api.router)
    app.include_router(voice_turns_api.router)
    return app
