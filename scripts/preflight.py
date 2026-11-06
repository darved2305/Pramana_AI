"""Check demo prerequisites without exposing credentials or spending Gnani credits by default."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from pramana_core.llm import read_env_file

ROOT = Path(__file__).resolve().parents[1]
MIB = 1024 * 1024


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def _env_check(env: dict[str, str]) -> Check:
    required = ["GNANI_API_KEY", "CORE_AUTOMATION_KEY"]
    provider = env.get("LLM_EXTRACTOR_PROVIDER", "none").strip().lower()
    if provider == "groq":
        required.append("GROQ_API_KEY")
    elif provider == "gemini":
        required.append("GEMINI_API_KEY")
    missing = [name for name in required if not env.get(name, "").strip()]
    if missing:
        return Check("Environment keys", False, "missing " + ", ".join(missing))
    optional = [name for name in ("GROQ_API_KEY", "GEMINI_API_KEY") if name not in required]
    configured = [name for name in optional if env.get(name, "").strip()]
    suffix = f"; optional keys set: {', '.join(configured)}" if configured else ""
    return Check("Environment keys", True, "required keys are present" + suffix)


def _ready_checks(client: httpx.Client, base_url: str) -> list[Check]:
    try:
        response = client.get(f"{base_url.rstrip('/')}/ready", follow_redirects=False)
        payload = response.json() if response.content else {}
    except (httpx.HTTPError, ValueError):
        return [
            Check("PostgreSQL", False, "core readiness endpoint could not be reached"),
            Check("Simulator", False, "core readiness endpoint could not be reached"),
            Check("Core /ready", False, "request failed"),
        ]

    if not isinstance(payload, dict):
        payload = {}
    checks = payload.get("checks", {})
    if not isinstance(checks, dict):
        checks = {}
    db_status = checks.get("database", "missing")
    sim_status = checks.get("simulator", "missing")
    db_ok = db_status == "ok"
    sim_ok = sim_status == "ok"
    core_ok = response.status_code == 200 and payload.get("status") == "ready"
    return [
        Check(
            "PostgreSQL",
            db_ok,
            "reachable" if db_ok else f"readiness reports {db_status}",
        ),
        Check(
            "Simulator",
            sim_ok,
            "reachable" if sim_ok else f"readiness reports {sim_status}",
        ),
        Check(
            "Core /ready",
            core_ok,
            "ready"
            if core_ok
            else f"HTTP {response.status_code}: {payload.get('status', 'unknown')}",
        ),
    ]


def _auth_check(client: httpx.Client, base_url: str, key: str) -> tuple[Check, bool]:
    if not key:
        return Check("Automation sign-in", False, "CORE_AUTOMATION_KEY is missing"), False
    try:
        response = client.get(
            f"{base_url.rstrip('/')}/v1/auth/session",
            headers={"X-Automation-Key": key},
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        return Check("Automation sign-in", False, f"request failed ({type(exc).__name__})"), False
    if response.status_code == 200:
        try:
            principal = response.json()
        except ValueError:
            principal = None
        if isinstance(principal, dict) and principal.get("method") == "automation":
            return Check("Automation sign-in", True, "automation key authenticated"), True
        return Check(
            "Automation sign-in", False, "server did not authenticate the automation key"
        ), False
    return Check(
        "Automation sign-in", False, f"staff endpoint returned HTTP {response.status_code}"
    ), False


def _budget_check(client: httpx.Client, base_url: str, key: str, authenticated: bool) -> Check:
    if not authenticated:
        return Check("Gnani budget", False, "unavailable because automation sign-in failed")
    try:
        response = client.get(
            f"{base_url.rstrip('/')}/v1/voice/usage",
            headers={"X-Automation-Key": key},
            follow_redirects=False,
        )
        if response.status_code != 200:
            return Check(
                "Gnani budget", False, f"usage endpoint returned HTTP {response.status_code}"
            )
        payload = response.json()
        spent = float(payload["spent_today_inr"])
        budget = float(payload["limits"]["daily_budget_inr"])
        if spent < 0 or budget <= 0:
            raise ValueError("invalid budget values")
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return Check("Gnani budget", False, "could not read today's guarded usage")
    remaining = max(0.0, budget - spent)
    return Check(
        "Gnani budget",
        remaining > 0,
        f"remaining Rs {remaining:.2f} of Rs {budget:.2f}",
    )


def _live_voice_check(client: httpx.Client, base_url: str, key: str) -> Check:
    headers = {"X-Automation-Key": key}
    try:
        tts = client.post(
            f"{base_url.rstrip('/')}/v1/voice/tts",
            headers=headers,
            json={"text": "hello", "language": "en-IN"},
            follow_redirects=False,
        )
        if tts.status_code != 200 or not tts.content.startswith(b"RIFF"):
            return Check("Gnani STT/TTS round trip", False, "Timbre synthesis failed")
        stt = client.post(
            f"{base_url.rstrip('/')}/v1/voice/stt",
            headers=headers,
            data={"language_codes": "en-IN,hi-IN", "codemix": "false"},
            files={"audio": ("preflight.wav", tts.content, "audio/wav")},
            follow_redirects=False,
        )
        if stt.status_code != 200:
            return Check("Gnani STT/TTS round trip", False, "Prisma transcription failed")
        result = stt.json()
        passed = isinstance(result, dict) and bool(str(result.get("transcript", "")).strip())
    except (httpx.HTTPError, ValueError, TypeError):
        passed = False
    return Check(
        "Gnani STT/TTS round trip",
        passed,
        "Timbre and Prisma round trip completed" if passed else "Prisma transcription failed",
    )


def _clock_check(
    client: httpx.Client,
    url: str,
    *,
    now: datetime,
    max_skew_s: float,
    date_reader: Callable[[httpx.Client, str], str | None],
) -> Check:
    if urlsplit(url).scheme.lower() != "https":
        return Check("Clock skew", False, "clock source must use HTTPS")
    try:
        value = date_reader(client, url)
        if not value:
            return Check("Clock skew", False, "HTTPS response has no Date header")
        server_time = parsedate_to_datetime(value)
        if server_time.tzinfo is None:
            server_time = server_time.replace(tzinfo=UTC)
        skew = abs((now - server_time.astimezone(UTC)).total_seconds())
    except (httpx.HTTPError, TypeError, ValueError, OverflowError):
        return Check("Clock skew", False, "could not read an HTTPS Date header")
    return Check(
        "Clock skew",
        skew <= max_skew_s,
        f"{skew:.1f} s from HTTPS Date (limit {max_skew_s:.1f} s)",
    )


def _read_date_header(client: httpx.Client, url: str) -> str | None:
    response = client.get(url, follow_redirects=False)
    return response.headers.get("date")


def collect_checks(
    args: Any,
    *,
    env: dict[str, str],
    client: httpx.Client,
    date_reader: Callable[[httpx.Client, str], str | None] = _read_date_header,
    disk_usage: Callable[[str | os.PathLike[str]], Any] = shutil.disk_usage,
    now: datetime | None = None,
) -> list[Check]:
    checks = [_env_check(env)]
    checks.extend(_ready_checks(client, args.url))
    key = env.get("CORE_AUTOMATION_KEY", "").strip()
    auth_check, authenticated = _auth_check(client, args.url, key)
    checks.append(auth_check)
    checks.append(_budget_check(client, args.url, key, authenticated))
    if args.live:
        if not authenticated:
            checks.append(
                Check(
                    "Gnani STT/TTS round trip",
                    False,
                    "unavailable because automation sign-in failed",
                )
            )
        elif not env.get("GNANI_API_KEY", "").strip():
            checks.append(Check("Gnani STT/TTS round trip", False, "GNANI_API_KEY is missing"))
        else:
            checks.append(_live_voice_check(client, args.url, key))

    try:
        usage = disk_usage(ROOT)
        free_mb = int(usage.free // MIB)
        checks.append(
            Check(
                "Disk space",
                free_mb >= args.min_disk_mb,
                f"{free_mb} MB free (minimum {args.min_disk_mb} MB)",
            )
        )
    except OSError as exc:
        checks.append(
            Check("Disk space", False, f"could not read disk space ({type(exc).__name__})")
        )

    clips_dir = Path(args.clips_dir)
    clips_exist = clips_dir.is_dir()
    checks.append(
        Check(
            "Voice bot clips", clips_exist, "folder exists" if clips_exist else "folder is missing"
        )
    )
    checks.append(
        _clock_check(
            client,
            args.clock_url,
            now=now or datetime.now(UTC),
            max_skew_s=args.max_clock_skew_s,
            date_reader=date_reader,
        )
    )
    return checks


def render_table(checks: list[Check]) -> str:
    name_width = max((len(check.name) for check in checks), default=5)
    lines = [f"{'STATUS':<6}  {'CHECK':<{name_width}}  RESULT"]
    lines.append(f"{'-' * 6}  {'-' * name_width}  {'-' * 60}")
    for check in checks:
        status = "PASS" if check.passed else "FAIL"
        lines.append(f"{status:<6}  {check.name:<{name_width}}  {check.detail}")
    return "\n".join(lines)


def _environment(root: Path = ROOT) -> dict[str, str]:
    values = read_env_file(root / ".env")
    values.update(os.environ)
    return values


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check Pramana demo prerequisites")
    parser.add_argument("--url", help="core base URL, local or staging")
    parser.add_argument("--clock-url", default="https://www.google.com/generate_204")
    parser.add_argument("--clips", type=Path, default=Path.home() / "pramana-voice-samples" / "bot")
    parser.add_argument("--min-disk-mb", type=int, default=512)
    parser.add_argument("--max-clock-skew-s", type=float, default=5.0)
    parser.add_argument(
        "--live", action="store_true", help="spend a small amount for one Gnani round trip"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parse_args(argv)
    env = _environment()
    args.url = (args.url or env.get("PRAMANA_CORE_URL") or "http://127.0.0.1:8000").rstrip("/")
    args.clips_dir = args.clips
    if args.min_disk_mb < 0 or args.max_clock_skew_s < 0:
        print("--min-disk-mb and --max-clock-skew-s must be non-negative", file=sys.stderr)
        return 2
    with httpx.Client(timeout=15.0, follow_redirects=False) as client:
        checks = collect_checks(args, env=env, client=client)
    print(render_table(checks))
    return 0 if all(check.passed for check in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
