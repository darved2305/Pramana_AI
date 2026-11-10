# No ``from __future__ import annotations``: FastAPI resolves dependency annotations at runtime.
"""Core service application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select

from pramana_contracts import CONTRACTS_VERSION
from pramana_domain.spec_storage import load_spec, spec_digest

from .account_rows import ModelTemplateRow
from .accounts import AccountService
from .api import accounts as accounts_api
from .api import auth as auth_api
from .api import consent as consent_api
from .api import directory as directory_api
from .api import domain_joins as domain_joins_api
from .api import evaluation as evaluation_api
from .api import home as home_api
from .api import investigations as investigations_api
from .api import invitations as invitations_api
from .api import members as members_api
from .api import packs as packs_api
from .api import people as people_api
from .api import site_builder as site_builder_api
from .api import site_investigations as site_investigations_api
from .api import site_voice as site_voice_api
from .api import sites as sites_api
from .api import stream as stream_api
from .api import voice as voice_api
from .api import voice_turns as voice_turns_api
from .api import workspace as workspace_api
from .auth.deps import participant_public_key
from .auth.google import GoogleSignIn
from .auth.oidc import GoogleOidc
from .auth.service import AuthService, LoginThrottle
from .body_limit import BodyLimitMiddleware
from .cursors import CursorCodec
from .db import Database, make_engine
from .directory import make_queries
from .domain_joins import DnsPythonResolver, DnsTxtResolver, DomainJoins
from .errors import install_error_handlers
from .investigations import InvestigationService
from .invitations import Invitations
from .language.extraction import RuleExtractor
from .language.hybrid import HybridExtractor
from .llm import LlmClient
from .mail import GmailSmtp
from .observability import RequestContextMiddleware, configure_logging, log
from .outbox import EmailRelay
from .people import SitePeople
from .runtime.broadcast import EventBroadcaster
from .runtime.recovery import recover
from .settings import Settings, get_settings
from .sim_client import SimClient
from .site_builder import SiteBuilder
from .site_models import StoredModels
from .vault import PersonVault, master_key
from .voice.conversation import QuestionAudioCache
from .voice.gnani import GnaniClient
from .voice.governor import DbLedger, GovernorLimits, VoiceGovernor
from .voice.media import ActiveSessions
from .workspace_lifecycle import WorkspaceLifecycle


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
    oidc_transport: httpx.AsyncBaseTransport | None = None,
    dns_txt_resolver: DnsTxtResolver | None = None,
) -> FastAPI:
    cfg = settings or get_settings()
    configure_logging(cfg.log_level, cfg.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(make_engine(cfg))
        if cfg.mode == "production":
            try:
                await db.require_runtime_role()
            except Exception:
                await db.dispose()
                raise
        sim = SimClient(
            cfg.sim_url,
            cfg.sim_operator_key.get_secret_value(),
            cfg.sim_timeout_s,
            transport=sim_transport,
            service_auth=cfg.sim_serverless_auth,
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
        app.state.cursor_codec = CursorCodec(cfg.participant_signing_key.get_secret_value())
        app.state.sim = sim
        app.state.gnani = gnani
        app.state.question_audio = QuestionAudioCache(
            disk_dir=Path(cfg.tts_cache_dir) if cfg.tts_cache_dir else None
        )
        app.state.vault = PersonVault(master_key(cfg))
        app.state.investigations = InvestigationService(
            db,
            sim,
            HybridExtractor(RuleExtractor(), _llm_extractor(cfg)),
            cfg.participant_signing_key.get_secret_value(),
            browser_sim_url=cfg.browser_sim_url,
            require_saved_models=cfg.mode == "production",
            vault=app.state.vault,
        )
        app.state.auth = AuthService(
            db,
            cfg.session_ttl_s,
            LoginThrottle(cfg.login_max_failures, cfg.login_lockout_s),
            idle_s=cfg.session_idle_ttl_s,
        )
        app.state.accounts = AccountService(db)
        app.state.workspace_lifecycle = WorkspaceLifecycle(db, app.state.vault)
        app.state.site_models = StoredModels(db)
        app.state.site_people = SitePeople(db, app.state.vault)
        app.state.invitations = Invitations(db, app.state.vault.master)
        can_send_email = cfg.mode != "test" and cfg.oidc_issuer == "https://accounts.google.com"
        app.state.mailer = (
            GmailSmtp(cfg.gmail_address, cfg.gmail_app_password)
            if can_send_email
            and cfg.invitation_link_base
            and cfg.gmail_address
            and cfg.gmail_app_password
            else None
        )
        app.state.email_relay = EmailRelay(db, app.state.mailer, app.state.vault.master)
        app.state.domain_joins = DomainJoins(
            db, dns_txt_resolver or DnsPythonResolver(), app.state.vault.master
        )
        app.state.site_builder = SiteBuilder(db, app.state.site_people)
        oidc = GoogleOidc(cfg, transport=oidc_transport)
        app.state.google_sign_in = GoogleSignIn(db, oidc, app.state.auth)
        app.state.participant_public_key = participant_public_key(
            cfg.participant_signing_key.get_secret_value()
        )
        app.state.console = make_queries(db, cfg.eval_reports_dir, app.state.vault)
        broadcaster = EventBroadcaster()
        db.commit_listeners.append(broadcaster.publish)
        app.state.broadcaster = broadcaster
        app.state.media_sessions = ActiveSessions()
        app.state.recovery = (
            (await recover(app.state.investigations)).as_dict() if cfg.recover_on_startup else None
        )
        log.info(
            "startup",
            mode=cfg.mode,
            gnani_configured=gnani.configured,
            auth_enforced=cfg.enforce_auth,
        )
        try:
            yield
        finally:
            broadcaster.close()
            await oidc.aclose()
            await gnani.aclose()
            await sim.aclose()
            await db.dispose()
            log.info("shutdown")

    app = FastAPI(title="Pramana core", version="0.1.0", lifespan=lifespan)

    def body_limit(path: str) -> int:
        if path == "/v1/voice/stt" or (
            (path.startswith("/v1/investigations/") or path.startswith("/v1/orgs/"))
            and path.endswith("/answers/voice")
        ):
            return cfg.voice_max_upload_bytes + 64 * 1024
        if path == "/v1/auth/login" or path.startswith("/v1/consent-links/"):
            return 64 * 1024
        return 4 * 1024 * 1024

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=[
            "Content-Type",
            "X-Request-ID",
            "X-Pramana-CSRF",
            "Authorization",
            "Idempotency-Key",
            "If-Match",
        ],
        expose_headers=["X-Request-ID", "ETag", "Idempotent-Replayed"],
    )
    app.add_middleware(
        BodyLimitMiddleware, limit_for_path=body_limit, cors_origins=cfg.cors_origins
    )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Liveness: the process is up. Does not touch dependencies."""
        return {"status": "ok", "contracts": CONTRACTS_VERSION}

    @app.get("/ready")
    async def ready(request: Request) -> JSONResponse:
        """Readiness: database and simulator reachable, saved templates intact and loadable."""
        checks: dict[str, str] = {}
        try:
            await request.app.state.db.ping()
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {type(exc).__name__}"
        checks["simulator"] = "ok" if await request.app.state.sim.health() else "unreachable"
        try:
            async with request.app.state.db.read() as session:
                template = await session.scalar(
                    select(ModelTemplateRow)
                    .where(ModelTemplateRow.purpose == "sandbox")
                    .order_by(ModelTemplateRow.version.desc())
                    .limit(1)
                )
            if template is None or spec_digest(template.spec) != template.spec_sha256:
                raise ValueError("saved template missing or corrupt")
            load_spec(template.spec)
            checks["models"] = "ok"
        except Exception as exc:
            checks["models"] = f"error: {type(exc).__name__}"
        checks["gnani"] = "configured" if request.app.state.gnani.configured else "not configured"
        ok = all(v == "ok" for k, v in checks.items() if k != "gnani")
        return JSONResponse(
            {"status": "ready" if ok else "not_ready", "checks": checks},
            status_code=200 if ok else 503,
        )

    app.include_router(auth_api.router)
    app.include_router(accounts_api.router)
    app.include_router(workspace_api.router)
    app.include_router(domain_joins_api.user_router)
    app.include_router(domain_joins_api.org_router)
    app.include_router(sites_api.router)
    app.include_router(site_builder_api.library)
    app.include_router(site_builder_api.router)
    app.include_router(people_api.router)
    app.include_router(consent_api.router)
    app.include_router(home_api.router)
    app.include_router(members_api.router)
    app.include_router(invitations_api.router)
    app.include_router(invitations_api.accept_router)
    app.include_router(site_investigations_api.router)
    app.include_router(site_voice_api.router)
    app.include_router(site_voice_api.sockets)
    if cfg.mode == "production":
        app.include_router(site_voice_api.account)
    if cfg.mode != "production":
        app.include_router(investigations_api.router)
        app.include_router(directory_api.router)
        app.include_router(evaluation_api.router)
        app.include_router(stream_api.router)
        app.include_router(packs_api.router)
        app.include_router(voice_api.router)
        app.include_router(voice_turns_api.router)
    return app
