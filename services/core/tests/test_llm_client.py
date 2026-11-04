"""LLM client: typed errors, bounded retries, schema checks and secret hygiene (no network)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

from pramana_core.llm import (
    LlmClient,
    LlmConfigError,
    LlmError,
    LlmProviderError,
    LlmQuotaExhaustedError,
    LlmRateLimitedError,
    LlmSchemaError,
    LlmTimeoutError,
    ProviderLimits,
    check_schema,
    redact,
)

KEY = "gsk_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"
SCHEMA = {
    "type": "object",
    "properties": {"outcome": {"type": "string", "enum": ["on", "off", "unknown"]}},
    "required": ["outcome"],
    "additionalProperties": False,
}
MSGS = [{"role": "user", "content": "is it on?"}]


def _reply(content: Any, status: int = 200) -> httpx.Response:
    text = content if isinstance(content, str) else json.dumps(content)
    return httpx.Response(
        status, json={"choices": [{"message": {"content": text}}], "usage": {"total_tokens": 9}}
    )


def _client(tmp_path: Path, handler: Any, **kw: Any) -> LlmClient:
    lim = ProviderLimits(requests_per_min=100, tokens_per_min=10**6, requests_per_day=100)
    return LlmClient(
        "groq",
        cache_dir=tmp_path,
        api_key=KEY,
        limits=lim,
        transport=httpx.MockTransport(handler),
        **kw,
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _s: None)


def test_all_errors_share_the_base_class_and_have_codes() -> None:
    kinds = [
        LlmConfigError,
        LlmTimeoutError,
        LlmRateLimitedError,
        LlmQuotaExhaustedError,
        LlmSchemaError,
        LlmProviderError,
    ]
    assert all(issubclass(k, LlmError) for k in kinds)
    assert len({k.code for k in kinds}) == len(kinds)


def test_missing_key_is_a_config_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    with pytest.raises(LlmConfigError):
        LlmClient("groq", cache_dir=tmp_path)
    with pytest.raises(LlmConfigError):
        LlmClient("nope", cache_dir=tmp_path, api_key="x")


def test_persistent_timeouts_raise_llm_timeout(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=req)

    with pytest.raises(LlmTimeoutError):
        _client(tmp_path, handler).complete_json(MSGS, SCHEMA, max_attempts=3)


def test_wall_clock_bound_stops_retrying_early(tmp_path: Path) -> None:
    calls = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=req)

    c = _client(tmp_path, handler, total_timeout_s=1.0)  # first backoff is 2 s
    with pytest.raises(LlmTimeoutError, match="gave up within"):
        c.complete_json(MSGS, SCHEMA, max_attempts=6)
    assert calls == 1


def test_connection_errors_are_provider_errors(tmp_path: Path) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(LlmProviderError):
        _client(tmp_path, handler).complete_json(MSGS, SCHEMA, max_attempts=2)


def test_persistent_429_is_rate_limited_and_daily_quota_is_exhausted(tmp_path: Path) -> None:
    with pytest.raises(LlmRateLimitedError):
        _client(tmp_path / "a", lambda _: httpx.Response(429, text="slow down")).complete_json(
            MSGS, SCHEMA, max_attempts=2
        )
    daily = httpx.Response(429, text="quota exceeded: requests per day")
    c = _client(tmp_path / "b", lambda _: daily)
    with pytest.raises(LlmQuotaExhaustedError, match="daily quota exhausted"):
        c.complete_json(MSGS, SCHEMA)
    with pytest.raises(LlmQuotaExhaustedError, match="daily request budget"):
        c.complete_json([{"role": "user", "content": "again"}], SCHEMA)


def test_pacing_beyond_the_wait_limit_is_rate_limited(tmp_path: Path) -> None:
    lim = ProviderLimits(requests_per_min=1, tokens_per_min=10**6, requests_per_day=100)
    c = LlmClient(
        "groq",
        cache_dir=tmp_path,
        api_key=KEY,
        limits=lim,
        max_wait_s=1.0,
        transport=httpx.MockTransport(lambda _: _reply({"outcome": "on"})),
    )
    c.complete_json(MSGS, SCHEMA)
    with pytest.raises(LlmRateLimitedError, match="pacing"):
        c.complete_json([{"role": "user", "content": "second"}], SCHEMA)


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        {"outcome": "maybe"},  # outside the enum
        {"hedge": "certain"},  # missing required field
        {"outcome": "on", "command": "dispatch"},  # extra field
        ["on"],  # not an object
    ],
)
def test_answers_outside_the_schema_are_schema_errors(tmp_path: Path, content: Any) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _reply(content)

    with pytest.raises(LlmSchemaError):
        _client(tmp_path, handler).complete_json(MSGS, SCHEMA, max_attempts=2)
    assert calls == 2
    assert not list(tmp_path.glob("*.json")) or all(
        "daily" in p.name for p in tmp_path.glob("*.json")
    )  # nothing invalid was cached


def test_malformed_provider_envelope_is_a_schema_error(tmp_path: Path) -> None:
    with pytest.raises(LlmSchemaError):
        _client(tmp_path, lambda _: httpx.Response(200, text="<html>oops")).complete_json(
            MSGS, SCHEMA, max_attempts=1
        )
    with pytest.raises(LlmSchemaError):
        _client(tmp_path, lambda _: httpx.Response(200, json={"choices": []})).complete_json(
            MSGS, SCHEMA, max_attempts=1
        )


def test_non_retryable_status_is_a_provider_error_with_status(tmp_path: Path) -> None:
    with pytest.raises(LlmProviderError) as info:
        _client(tmp_path, lambda _: httpx.Response(403, text="forbidden")).complete_json(
            MSGS, SCHEMA
        )
    assert info.value.status == 403


def test_keys_never_appear_in_errors_repr_or_logs(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    echo = f'{{"error": "invalid api key {KEY}", "auth": "Bearer {KEY}"}}'
    c = _client(tmp_path, lambda _: httpx.Response(401, text=echo))
    caplog.set_level(logging.DEBUG)
    with pytest.raises(LlmProviderError) as info:
        c.complete_json(MSGS, SCHEMA)
    assert KEY not in str(info.value)
    assert "[redacted]" in str(info.value)
    assert KEY not in repr(c)
    assert KEY not in caplog.text


def test_redact_handles_known_key_shapes() -> None:
    google = "AIza" + "S" * 35
    text = redact(f"k={google} groq={KEY} Authorization: Bearer abcdefgh1234", "")
    assert google not in text
    assert KEY not in text
    assert "abcdefgh1234" not in text


def test_check_schema_accepts_valid_answers() -> None:
    check_schema({"outcome": "off"}, SCHEMA)
    check_schema({"anything": 1}, {})
