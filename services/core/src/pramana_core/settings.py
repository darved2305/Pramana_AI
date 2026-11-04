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

    cors_origins: list[str] = Field(default=["http://localhost:3000"], alias="CORS_ORIGINS")

    @field_validator("gnani_api_key", mode="before")
    @classmethod
    def _empty_is_none(cls, v: object) -> object:
        return None if v in ("", None) else v

    @property
    def browser_sim_url(self) -> str:
        return self.sim_public_url or self.sim_url


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
