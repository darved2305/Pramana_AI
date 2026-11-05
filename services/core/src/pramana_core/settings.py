"""Validated runtime configuration. Secrets live only in the core's environment."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    mode: Literal["dev", "test", "demo"] = Field(default="dev", alias="PRAMANA_MODE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_json: bool = Field(default=True, alias="LOG_JSON")

    database_url: str = Field(
        default="postgresql+asyncpg://pramana@localhost:5433/pramana", alias="DATABASE_URL"
    )
    db_pool_size: int = Field(default=5, ge=1, le=50, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=5, ge=0, le=50, alias="DB_MAX_OVERFLOW")
    db_pool_timeout_s: float = Field(default=5.0, gt=0, alias="DB_POOL_TIMEOUT_S")

    sim_url: str = Field(default="http://127.0.0.1:8100", alias="SIM_URL")
    sim_public_url: str | None = Field(default=None, alias="SIM_PUBLIC_URL")
    """Simulator URL as reachable from participants' browsers (defaults to ``sim_url``)."""
    sim_operator_key: SecretStr = Field(alias="SIM_OPERATOR_KEY")
    sim_timeout_s: float = Field(default=5.0, gt=0, alias="SIM_TIMEOUT_S")
    participant_signing_key: SecretStr = Field(alias="PARTICIPANT_SIGNING_KEY")
    """Ed25519 private key (base64url, raw 32 bytes). The simulator gets the public half."""

    gnani_api_key: SecretStr | None = Field(default=None, alias="GNANI_API_KEY")
    gnani_base_url: str = Field(default="https://api.vachana.ai", alias="GNANI_BASE_URL")
    gnani_timeout_s: float = Field(default=15.0, gt=0, alias="GNANI_TIMEOUT_S")
    gnani_rest_max_inflight: int = Field(default=1, ge=1, le=16, alias="GNANI_REST_MAX_INFLIGHT")
    """Simultaneous REST calls. Gnani's documented 429 says one active request at a time."""
    gnani_stt_rest_per_min: int = Field(default=50, ge=1, le=60, alias="GNANI_STT_REST_PER_MIN")
    gnani_tts_per_min: int = Field(default=50, ge=1, le=60, alias="GNANI_TTS_PER_MIN")
    """Account limit is 60 requests/minute for each; we keep headroom."""
    gnani_max_streams: int = Field(default=16, ge=1, le=20, alias="GNANI_MAX_STREAMS")
    """Account limit is 20 concurrent realtime sessions."""
    voice_daily_budget_inr: float = Field(default=150.0, gt=0, alias="VOICE_DAILY_BUDGET_INR")
    voice_max_stream_s: float = Field(default=300.0, gt=0, le=900, alias="VOICE_MAX_STREAM_S")
    voice_max_upload_bytes: int = Field(default=2_000_000, alias="VOICE_MAX_UPLOAD_BYTES")

    llm_extractor_provider: Literal["gemini", "groq", "none"] = Field(
        default="none", alias="LLM_EXTRACTOR_PROVIDER"
    )
    """Second-opinion extractor for answers the rules cannot map. ``none`` = rules only."""
    llm_extractor_model: str | None = Field(default=None, alias="LLM_EXTRACTOR_MODEL")
    gemini_api_key: SecretStr | None = Field(default=None, alias="GEMINI_API_KEY")
    groq_api_key: SecretStr | None = Field(default=None, alias="GROQ_API_KEY")
    llm_cache_dir: str = Field(default=".cache/llm", alias="LLM_CACHE_DIR")
    tts_cache_dir: str = Field(default=".cache/tts", alias="TTS_CACHE_DIR")
    """Question audio kept across restarts (empty: memory only)."""

    event_stream_heartbeat_s: float = Field(
        default=15.0, gt=0, le=25, alias="EVENT_STREAM_HEARTBEAT_S"
    )
    """Below the 30 s idle timeout of proxied requests in Next.js rewrites."""
    event_stream_max_s: float = Field(default=1800.0, gt=0, alias="EVENT_STREAM_MAX_S")
    """Streams end (with ``bye``) after this long; clients reconnect and resume."""
    event_stream_stall_s: float = Field(default=10.0, gt=0, alias="EVENT_STREAM_STALL_S")
    """A client that does not read for this long is dropped; it resumes on reconnect."""
    recover_on_startup: bool = Field(default=True, alias="RECOVER_ON_STARTUP")

    cors_origins: list[str] = Field(default=["http://localhost:3000"], alias="CORS_ORIGINS")

    auth_required: bool | None = Field(default=None, alias="AUTH_REQUIRED")
    """Enforce sign-in and roles. Unset means: on, except in ``PRAMANA_MODE=test``, where the
    engine and runtime suites exercise behaviour, not access (the auth suite turns it on)."""
    automation_key: SecretStr | None = Field(default=None, alias="CORE_AUTOMATION_KEY")
    """Shared secret for scripts and bots (``X-Automation-Key``): acts as operator and approver.
    Never sent to the browser."""
    session_ttl_s: int = Field(default=12 * 3600, ge=60, le=7 * 24 * 3600, alias="SESSION_TTL_S")
    session_cookie_secure: bool | None = Field(default=None, alias="SESSION_COOKIE_SECURE")
    """Mark the session cookie ``Secure``. Unset means: only in ``PRAMANA_MODE=demo`` (HTTPS)."""
    login_max_failures: int = Field(default=5, ge=1, le=100, alias="LOGIN_MAX_FAILURES")
    login_lockout_s: float = Field(default=300.0, gt=0, alias="LOGIN_LOCKOUT_S")
    eval_reports_dir: str = Field(default="eval/reports", alias="EVAL_REPORTS_DIR")

    @field_validator(
        "gnani_api_key", "gemini_api_key", "groq_api_key", "automation_key", mode="before"
    )
    @classmethod
    def _empty_is_none(cls, v: object) -> object:
        return None if v in ("", None) else v

    @property
    def enforce_auth(self) -> bool:
        return self.mode != "test" if self.auth_required is None else self.auth_required

    @property
    def secure_cookies(self) -> bool:
        return (
            self.mode == "demo"
            if self.session_cookie_secure is None
            else self.session_cookie_secure
        )

    @property
    def browser_sim_url(self) -> str:
        return self.sim_public_url or self.sim_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
