"""Preflight checks stay safe to test without real services or Gnani calls."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import preflight  # noqa: E402
from preflight import Check, collect_checks, render_table  # noqa: E402


def fake_client() -> tuple[httpx.Client, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/ready":
            return httpx.Response(
                200,
                json={
                    "status": "ready",
                    "checks": {"database": "ok", "simulator": "ok", "packs": "ok"},
                },
            )
        if request.url.path == "/v1/auth/session":
            return httpx.Response(200, json={"method": "automation"})
        if request.url.path == "/v1/voice/usage":
            return httpx.Response(
                200,
                json={
                    "spent_today_inr": 12.5,
                    "limits": {"daily_budget_inr": 150.0},
                },
            )
        if request.url.path == "/v1/voice/tts":
            return httpx.Response(200, content=b"RIFFfake-wav")
        if request.url.path == "/v1/voice/stt":
            return httpx.Response(200, json={"transcript": "नमस्ते", "detected_language": "hi-IN"})
        if request.url.host == "clock.test":
            return httpx.Response(200, headers={"Date": "Fri, 06 Nov 2026 12:00:00 GMT"})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(respond)), requests


def options(
    *, live: bool = False, clips_dir: Path, clock_url: str = "https://clock.test/date"
) -> object:
    return SimpleNamespace(
        url="https://core.test",
        clock_url=clock_url,
        max_clock_skew_s=5.0,
        min_disk_mb=1,
        clips_dir=clips_dir,
        live=live,
    )


def env() -> dict[str, str]:
    return {
        "GNANI_API_KEY": "gnani-secret-value",
        "CORE_AUTOMATION_KEY": "automation-secret-value",
        "LLM_EXTRACTOR_PROVIDER": "none",
    }


def collect(
    args: object,
    client: httpx.Client,
    *,
    environment: dict[str, str] | None = None,
    date: str | None = "Fri, 06 Nov 2026 12:00:00 GMT",
) -> list[Check]:
    return collect_checks(
        args,
        env=env() if environment is None else environment,
        client=client,
        date_reader=lambda _client, _url: date,
        disk_usage=lambda _path: SimpleNamespace(free=2_000_000_000),
        now=datetime(2026, 11, 6, 12, 0, tzinfo=UTC),
    )


def test_preflight_checks_services_budget_and_local_requirements_without_leaking_keys(
    tmp_path: Path,
) -> None:
    clips = tmp_path / "bot-clips"
    clips.mkdir()
    client, requests = fake_client()
    try:
        checks = collect(options(clips_dir=clips), client)
    finally:
        client.close()

    assert all(check.passed for check in checks)
    output = render_table(checks)
    assert "remaining Rs 137.50" in output
    assert "gnani-secret-value" not in output
    assert "automation-secret-value" not in output
    assert not any(request.url.path in {"/v1/voice/tts", "/v1/voice/stt"} for request in requests)


def test_live_preflight_runs_one_timbre_and_prisma_round_trip(tmp_path: Path) -> None:
    clips = tmp_path / "bot-clips"
    clips.mkdir()
    client, requests = fake_client()
    try:
        checks = collect(options(live=True, clips_dir=clips), client)
    finally:
        client.close()

    assert all(check.passed for check in checks)
    paths = [request.url.path for request in requests]
    assert paths.count("/v1/voice/tts") == 1
    assert paths.count("/v1/voice/stt") == 1
    output = render_table(checks).lower()
    assert "latency" not in output
    assert "accuracy" not in output


def test_missing_keys_and_failed_dependencies_are_reported_as_failures(tmp_path: Path) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(503, json={"status": "down"}))
    )
    try:
        checks = collect(
            options(clips_dir=tmp_path / "missing-clips"),
            client,
            environment={"LLM_EXTRACTOR_PROVIDER": "none"},
            date=None,
        )
    finally:
        client.close()

    assert any(not check.passed and check.name == "Environment keys" for check in checks)
    assert any(not check.passed and check.name == "PostgreSQL" for check in checks)
    assert any(not check.passed and check.name == "Voice bot clips" for check in checks)


def test_cli_returns_nonzero_when_any_preflight_check_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight, "_environment", lambda: {})
    monkeypatch.setattr(
        preflight, "collect_checks", lambda *_args, **_kwargs: [Check("Core /ready", False, "down")]
    )

    assert preflight.main([]) == 1


def test_auth_check_rejects_an_open_server_even_when_a_key_is_set() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={"method": "open"}))
    )
    try:
        check, authenticated = preflight._auth_check(client, "https://core.test", "wrong-key")
    finally:
        client.close()
    assert not check.passed
    assert not authenticated


def test_auth_check_does_not_follow_a_redirect_with_the_automation_key() -> None:
    seen: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "core.test":
            return httpx.Response(302, headers={"Location": "https://other.test/session"})
        return httpx.Response(200, json={"method": "automation"})

    client = httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=True)
    try:
        check, authenticated = preflight._auth_check(client, "https://core.test", "private-key")
    finally:
        client.close()
    assert not check.passed
    assert not authenticated
    assert [request.url.host for request in seen] == ["core.test"]


def test_clock_check_requires_an_https_date_source(tmp_path: Path) -> None:
    client, _ = fake_client()
    try:
        checks = collect(options(clips_dir=tmp_path, clock_url="http://clock.test/date"), client)
    finally:
        client.close()
    clock = next(check for check in checks if check.name == "Clock skew")
    assert not clock.passed
    assert "HTTPS" in clock.detail


def test_runbook_does_not_claim_automated_phone_or_latency_checks() -> None:
    text = (ROOT / "docs" / "DEMO.md").read_text(encoding="utf-8")
    preflight_line = next(
        line for line in text.splitlines() if "**Pre-flight (`make preflight`)" in line
    )
    assert "mic permission on every phone" not in preflight_line
    assert "(< 2 s)" not in preflight_line
