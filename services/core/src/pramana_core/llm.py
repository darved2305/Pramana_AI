"""A free-tier-safe LLM client for OpenAI-compatible endpoints (Gemini, Groq).

Design for free tiers, where quota and capacity are the binding constraints:

* Stay under quota instead of hitting it: sliding windows for requests/minute and tokens/minute,
  a per-day request counter persisted on disk, and Groq's live ``x-ratelimit-*`` headers
  (remaining tokens/requests and reset times) override the static limits when present.
* Never pay twice: every response is cached on disk by a hash of (model, messages, schema), so
  an interrupted benchmark resumes for free and re-runs are reproducible.
* Free-tier capacity is not guaranteed (Gemini returned 503 "high demand" on 2026-11-04): 429,
  500 and 503 are retried with capped backoff on the *same* model, honouring ``Retry-After``.
  The model is pinned per run so results are attributable; every call records which model
  answered.
* Output is strict JSON (``response_format: json_schema``) and parsed; the caller validates it.

Measured on 2026-11-04 (headers): Groq ``openai/gpt-oss-120b`` 1,000 requests/day and 8,000
tokens/minute. Gemini free-tier numbers are shown only in AI Studio, so they are configurable.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


class LlmError(RuntimeError):
    """Base class. ``code`` is stable for callers and logs; the message never holds a key."""

    code = "LLM_ERROR"


class LlmConfigError(LlmError):
    code = "LLM_NOT_CONFIGURED"


class LlmTimeoutError(LlmError):
    code = "LLM_TIMEOUT"


class LlmRateLimitedError(LlmError):
    """Per-minute pacing or provider 429 that did not clear in the allowed time."""

    code = "LLM_RATE_LIMITED"


class LlmQuotaExhaustedError(LlmError):
    """The daily cap (ours or the provider's) is used up: nothing is sent until tomorrow."""

    code = "LLM_QUOTA_EXHAUSTED"


class LlmSchemaError(LlmError):
    """The model answered, but not with JSON that fits the requested schema."""

    code = "SCHEMA_FAIL"


class LlmProviderError(LlmError):
    """A provider failure: a non-retryable response, or 5xx/connection errors that persisted."""

    code = "LLM_PROVIDER_ERROR"

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


_KEY_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),  # Google API keys
    re.compile(r"gsk_[0-9A-Za-z]{20,}"),  # Groq keys
    re.compile(r"sk-[0-9A-Za-z_\-]{20,}"),
    re.compile(r"(?i)bearer\s+[0-9A-Za-z._\-]{8,}"),
)


def redact(text: str, *secrets: str) -> str:
    """Remove API keys from text that may be logged or raised (provider bodies can echo them)."""
    for secret in secrets:
        if secret and len(secret) >= 4:
            text = text.replace(secret, "[redacted]")
    for pat in _KEY_PATTERNS:
        text = pat.sub("[redacted]", text)
    return text


def check_schema(data: Any, schema: dict[str, Any]) -> None:
    """Shallow check of the schema features our roles use: object, required, enums, no extras.

    ``strict`` structured output should already guarantee this, but free-tier models do not
    always honour it, and an out-of-enum value must never reach a caller as if it were valid.
    """
    if schema.get("type") == "object" and not isinstance(data, dict):
        raise LlmSchemaError(f"expected a JSON object, got {type(data).__name__}")
    if not isinstance(data, dict):
        return
    missing = [k for k in schema.get("required", []) if k not in data]
    if missing:
        raise LlmSchemaError(f"missing required fields {missing}")
    props: dict[str, Any] = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        extra = sorted(set(data) - set(props))
        if extra:
            raise LlmSchemaError(f"unexpected fields {extra}")
    for name, spec in props.items():
        if (
            name in data
            and isinstance(spec, dict)
            and "enum" in spec
            and data[name] not in spec["enum"]
        ):
            raise LlmSchemaError(f"{name}={data[name]!r} is not one of {spec['enum']}")


@dataclass(frozen=True)
class ProviderLimits:
    requests_per_min: int
    tokens_per_min: int
    requests_per_day: int


PROVIDERS: dict[str, tuple[str, str, ProviderLimits]] = {
    # name: (base URL, API key env var, conservative limits)
    "groq": (
        "https://api.groq.com/openai/v1",
        "GROQ_API_KEY",
        ProviderLimits(requests_per_min=25, tokens_per_min=7_500, requests_per_day=950),
    ),
    "gemini": (
        "https://generativelanguage.googleapis.com/v1beta/openai",
        "GEMINI_API_KEY",
        # Free tier, per model and day: gemini-3.5-flash allowed 20 (its 429 said "limit: 20" on
        # 2026-11-04). Other models default to the same until their limit is known.
        ProviderLimits(requests_per_min=8, tokens_per_min=200_000, requests_per_day=20),
    ),
}
DEFAULT_MODELS = {"groq": "openai/gpt-oss-120b", "gemini": "gemini-3.5-flash"}


def _duration_s(value: str) -> float:
    """Parse Groq reset values such as ``"1m26.4s"``, ``"4.229s"`` or ``"750ms"``."""
    total = 0.0
    for num, unit in re.findall(r"([\d.]+)(ms|h|m|s)", value):
        total += float(num) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return total


def read_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


@dataclass
class _Budget:
    limits: ProviderLimits
    day_file: Path
    _requests: deque[float] = field(default_factory=deque)
    _tokens: deque[tuple[float, int]] = field(default_factory=deque)
    _header_block_until: float = 0.0

    def _day_key(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def used_today(self) -> int:
        if not self.day_file.exists():
            return 0
        data = json.loads(self.day_file.read_text(encoding="utf-8"))
        return int(data.get(self._day_key(), 0))

    def exhaust_today(self) -> None:
        """The provider said the daily quota is used up: stop sending until tomorrow."""
        data = (
            json.loads(self.day_file.read_text(encoding="utf-8")) if self.day_file.exists() else {}
        )
        data[self._day_key()] = max(int(data.get(self._day_key(), 0)), self.limits.requests_per_day)
        self.day_file.write_text(json.dumps(data), encoding="utf-8")

    def _count_today(self) -> None:
        data = (
            json.loads(self.day_file.read_text(encoding="utf-8")) if self.day_file.exists() else {}
        )
        data[self._day_key()] = int(data.get(self._day_key(), 0)) + 1
        self.day_file.write_text(json.dumps(data), encoding="utf-8")

    def wait_for_slot(self, est_tokens: int, max_wait_s: float | None = None) -> None:
        if self.used_today() >= self.limits.requests_per_day:
            raise LlmQuotaExhaustedError(
                f"daily request budget ({self.limits.requests_per_day}) used"
            )
        while True:
            now = time.monotonic()
            while self._requests and now - self._requests[0] >= 60:
                self._requests.popleft()
            while self._tokens and now - self._tokens[0][0] >= 60:
                self._tokens.popleft()
            waits = [self._header_block_until - now]
            if len(self._requests) >= self.limits.requests_per_min:
                waits.append(60 - (now - self._requests[0]))
            if (
                sum(t for _, t in self._tokens) + est_tokens > self.limits.tokens_per_min
                and self._tokens
            ):
                waits.append(60 - (now - self._tokens[0][0]))
            wait = max(waits)
            if max_wait_s is not None and wait > max_wait_s:
                raise LlmRateLimitedError(
                    f"quota pacing would wait {wait:.0f}s (limit {max_wait_s:.0f}s)"
                )
            if wait <= 0:
                self._requests.append(now)
                self._count_today()
                return
            time.sleep(min(wait, 60) + 0.05)

    def record(self, tokens: int, headers: httpx.Headers) -> None:
        now = time.monotonic()
        self._tokens.append((now, tokens))
        remaining = headers.get("x-ratelimit-remaining-tokens")
        reset = headers.get("x-ratelimit-reset-tokens")
        if remaining is not None and reset and int(remaining) < 1_500:
            self._header_block_until = max(self._header_block_until, now + _duration_s(reset))
        if headers.get("x-ratelimit-remaining-requests") == "0":
            reset_r = headers.get("x-ratelimit-reset-requests", "60s")
            self._header_block_until = max(self._header_block_until, now + _duration_s(reset_r))


@dataclass
class LlmResult:
    data: dict[str, Any]
    model: str
    cached: bool
    total_tokens: int


class LlmClient:
    def __init__(
        self,
        provider: str,
        model: str | None = None,
        *,
        cache_dir: Path,
        api_key: str | None = None,
        timeout_s: float = 40.0,
        max_wait_s: float | None = None,
        total_timeout_s: float | None = None,
        limits: ProviderLimits | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if provider not in PROVIDERS:
            raise LlmConfigError(f"unknown provider {provider}; choose from {sorted(PROVIDERS)}")
        base, key_var, default_limits = PROVIDERS[provider]
        key = api_key or os.environ.get(key_var) or read_env_file(Path(".env")).get(key_var)
        if not key:
            raise LlmConfigError(f"{key_var} is not set")
        self._key = key
        self.total_timeout_s = total_timeout_s
        """Wall-clock bound on one ``complete_json`` call including retries (interactive use)."""
        self.provider, self.model = provider, model or DEFAULT_MODELS[provider]
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        safe_model = re.sub(r"[^A-Za-z0-9.-]+", "_", self.model)
        self._budget = _Budget(
            limits or default_limits, cache_dir / f"{provider}_{safe_model}_daily.json"
        )
        self._http = httpx.Client(
            base_url=base,
            timeout=timeout_s,
            transport=transport,
            headers={"Authorization": f"Bearer {key}"},
        )
        self.calls = 0
        self.cache_hits = 0
        self.max_wait_s = max_wait_s
        self._send_reasoning = True
        """Ask for low reasoning effort; dropped for models that reject it (e.g. Gemma)."""
        """Interactive callers set this: fail fast (and fall back) instead of waiting on quota."""
        self._lock = threading.Lock()  # budget state is shared by worker threads

    def _cache_path(self, payload: dict[str, Any]) -> Path:
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        name: str = "answer",
        max_attempts: int = 6,
    ) -> LlmResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            **({"reasoning_effort": "low"} if self._send_reasoning else {}),
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": name, "strict": True, "schema": schema},
            },
        }
        cache = self._cache_path(payload)
        if cache.exists():
            self.cache_hits += 1
            stored = json.loads(cache.read_text(encoding="utf-8"))
            return LlmResult(stored["data"], stored["model"], True, stored.get("tokens", 0))
        est = sum(len(m["content"]) for m in messages) // 3 + 600  # prompt + low reasoning
        backoff = 2.0
        last = ""
        last_kind: type[LlmError] = LlmError
        started = time.monotonic()

        def pause(seconds: float) -> None:
            """Back off, unless that would exceed the caller's wall-clock bound."""
            if self.total_timeout_s is not None and (
                time.monotonic() - started + seconds > self.total_timeout_s
            ):
                raise last_kind(self._safe(f"gave up within {self.total_timeout_s:g}s: {last}"))
            time.sleep(seconds)

        for _ in range(max_attempts):
            with self._lock:
                self._budget.wait_for_slot(est, self.max_wait_s)
            try:
                r = self._http.post("/chat/completions", json=payload)
            except httpx.TimeoutException:
                last, last_kind = "timeout", LlmTimeoutError
                pause(backoff)
                backoff = min(backoff * 2, 60)
                continue
            except httpx.TransportError as exc:
                last, last_kind = f"connection error ({type(exc).__name__})", LlmProviderError
                pause(backoff)
                backoff = min(backoff * 2, 60)
                continue
            self.calls += 1
            body_json: Any = None
            if r.status_code == 200:
                try:
                    body_json = r.json()
                except json.JSONDecodeError:
                    body_json = None
            usage = (body_json.get("usage") or {}) if isinstance(body_json, dict) else {}
            with self._lock:
                self._budget.record(int(usage.get("total_tokens", est)), r.headers)
            if r.status_code == 200:
                content = ""
                try:
                    content = body_json["choices"][0]["message"].get("content") or ""
                    data = json.loads(content)
                    check_schema(data, schema)
                except (TypeError, KeyError, IndexError, AttributeError) as exc:
                    last, last_kind = f"malformed response ({type(exc).__name__})", LlmSchemaError
                    continue
                except json.JSONDecodeError:
                    last, last_kind = f"invalid JSON: {content[:120]!r}", LlmSchemaError
                    continue
                except LlmSchemaError as exc:
                    last, last_kind = str(exc), LlmSchemaError
                    continue
                tokens = int(usage.get("total_tokens", 0))
                cache.write_text(
                    json.dumps(
                        {"data": data, "model": self.model, "tokens": tokens}, ensure_ascii=False
                    ),
                    encoding="utf-8",
                )
                return LlmResult(data, self.model, False, tokens)
            last = f"HTTP {r.status_code}: {r.text[:200]}"
            body = r.text.lower()
            if r.status_code == 429 and _daily_limit(body):
                # A daily quota cannot recover by backing off: fail fast, remember it.
                with self._lock:
                    self._budget.exhaust_today()
                raise LlmQuotaExhaustedError(f"daily quota exhausted for {self.model}")
            if r.status_code in (429, 500, 502, 503, 504):
                last_kind = LlmRateLimitedError if r.status_code == 429 else LlmProviderError
                retry_after = r.headers.get("retry-after")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else backoff
                if wait > MAX_RETRY_WAIT_S:
                    # A wait this long is a quota window, not a blip: fail now, do not sleep.
                    raise last_kind(self._safe(f"provider asks to wait {wait:.0f}s: {last}"))
                pause(wait)
                backoff = min(backoff * 2, 60)
                continue
            if (
                r.status_code == 400
                and self._send_reasoning
                and ("thinking level" in body or "reasoning" in body)
            ):
                # This model has no reasoning control: retry once without it, remember that.
                self._send_reasoning = False
                payload.pop("reasoning_effort", None)
                cache = self._cache_path(payload)
                if cache.exists():
                    stored = json.loads(cache.read_text(encoding="utf-8"))
                    return LlmResult(stored["data"], stored["model"], True, stored.get("tokens", 0))
                continue
            raise LlmProviderError(self._safe(last), r.status_code)
        raise last_kind(self._safe(f"gave up after {max_attempts} attempts: {last}"))

    def _safe(self, text: str) -> str:
        return redact(text, self._key)

    def __repr__(self) -> str:  # never show the key, even in debug output
        return f"LlmClient(provider={self.provider!r}, model={self.model!r})"


MAX_RETRY_WAIT_S = 120.0
"""Longest provider-requested wait the client will sleep through before giving up."""


def _daily_limit(body: str) -> bool:
    """A 429 about a per-day limit: backing off cannot help until the window resets.

    Gemini says "Quota exceeded ... free_tier_requests"; Groq says "Rate limit reached ... on
    tokens per day (TPD)" or "requests per day (RPD)", without the word "quota".
    """
    b = body.lower()
    return (
        "per day" in b or "perday" in b or "free_tier_requests" in b or "(tpd)" in b or "(rpd)" in b
    )
