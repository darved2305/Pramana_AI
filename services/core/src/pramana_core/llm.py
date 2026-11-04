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
    pass


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
        ProviderLimits(requests_per_min=8, tokens_per_min=200_000, requests_per_day=240),
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

    def _count_today(self) -> None:
        data = (
            json.loads(self.day_file.read_text(encoding="utf-8")) if self.day_file.exists() else {}
        )
        data[self._day_key()] = int(data.get(self._day_key(), 0)) + 1
        self.day_file.write_text(json.dumps(data), encoding="utf-8")

    def wait_for_slot(self, est_tokens: int, max_wait_s: float | None = None) -> None:
        if self.used_today() >= self.limits.requests_per_day:
            raise LlmError(f"daily request budget ({self.limits.requests_per_day}) used")
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
                raise LlmError(f"quota pacing would wait {wait:.0f}s (limit {max_wait_s:.0f}s)")
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
        limits: ProviderLimits | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if provider not in PROVIDERS:
            raise LlmError(f"unknown provider {provider}; choose from {sorted(PROVIDERS)}")
        base, key_var, default_limits = PROVIDERS[provider]
        key = api_key or os.environ.get(key_var) or read_env_file(Path(".env")).get(key_var)
        if not key:
            raise LlmError(f"{key_var} is not set")
        self.provider, self.model = provider, model or DEFAULT_MODELS[provider]
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        self._budget = _Budget(limits or default_limits, cache_dir / f"{provider}_daily.json")
        self._http = httpx.Client(
            base_url=base,
            timeout=timeout_s,
            transport=transport,
            headers={"Authorization": f"Bearer {key}"},
        )
        self.calls = 0
        self.cache_hits = 0
        self.max_wait_s = max_wait_s
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
            "reasoning_effort": "low",
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
        for _ in range(max_attempts):
            with self._lock:
                self._budget.wait_for_slot(est, self.max_wait_s)
            try:
                r = self._http.post("/chat/completions", json=payload)
            except httpx.TimeoutException:
                last = "timeout"
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            self.calls += 1
            usage = (r.json().get("usage") or {}) if r.status_code == 200 else {}
            with self._lock:
                self._budget.record(int(usage.get("total_tokens", est)), r.headers)
            if r.status_code == 200:
                content = r.json()["choices"][0]["message"].get("content") or ""
                try:
                    data = json.loads(content)
                except json.JSONDecodeError:
                    last = f"invalid JSON: {content[:120]!r}"
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
            if r.status_code in (429, 500, 502, 503, 504):
                retry_after = r.headers.get("retry-after")
                time.sleep(float(retry_after) if retry_after and retry_after.isdigit() else backoff)
                backoff = min(backoff * 2, 60)
                continue
            raise LlmError(last)
        raise LlmError(f"gave up after {max_attempts} attempts: {last}")
