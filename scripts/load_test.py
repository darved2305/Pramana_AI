"""Load test: three voice calls at once, investigation after investigation, for N minutes.

Free: Gnani is emulated (``scripts/gnani_emulator.py``); everything else is real. A real
simulator and a real core run as separate processes on a dedicated database (``pramana_load``,
recreated each run, never the development one), with fresh keys. The three voice bots of
``scripts/voice_bot_run.py`` take their calls over the real call sockets and speak clips whose
audio carries their answer, so each answer crosses the call socket, the per-question recognizer
session, the second decode, the extractor, the engine, approval, repair and verification.

Checked, per run and overall:
- every run ends verified and correct on reveal, and its replay is byte-identical;
- no call socket failed (a bot error, an unexpected close, an exception);
- the voice governor's stream cap held (emulator: most recognizer sessions at once);
- the core's memory (working set) over time.

Writes ``<out>/summary.json`` and ``<out>/report.md``. Emulated timings are not Gnani's and
are not reported.

    uv run python scripts/load_test.py --minutes 10 --out eval/reports/load-YYYY-MM-DD
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import math
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import db_guard  # noqa: E402
import dev_db  # noqa: E402
import gnani_emulator  # noqa: E402

from pramana_contracts.tokens import (  # noqa: E402
    generate_private_key_b64,
    private_key_from_b64,
    public_key_b64,
)
from pramana_core.language.extraction import RuleExtractor  # noqa: E402

# One answer per observable value, in the bots' clip languages; checked against the extractor.
ANSWERS: dict[str, dict[str, str]] = {
    "hi": {
        "yes": "हाँ, खुल रही है",
        "no": "नहीं, नहीं खुल रही",
        "on": "हाँ, चालू है",
        "off": "बंद है",
        "green": "हरी हैं",
        "amber": "नारंगी हैं",
        "red": "लाल है",
        "up": "ऊपर है",
        "tripped": "ट्रिप होकर नीचे है",
        "no_network": "दिख ही नहीं रहा",
        "stuck_connecting": "कनेक्ट होने पर अटका है",
        "connected": "कनेक्टेड है",
    },
    "mr": {
        "yes": "हो, उघडतं",
        "no": "नाही उघडत",
        "on": "चालू आहे",
        "off": "बंद आहे",
        "green": "हिरवे दिवे आहेत",
        "amber": "नारंगी आहेत",
        "red": "लाल आहे",
        "up": "वर आहे",
        "tripped": "ट्रिप होऊन खाली आहे",
        "no_network": "दिसतच नाही",
        "stuck_connecting": "कनेक्ट होताना अडकलंय",
        "connected": "कनेक्टेड आहे",
    },
}
OUTCOME_SETS = [
    ["yes", "no"],
    ["on", "off"],
    ["green", "amber", "off"],
    ["green", "red", "off"],
    ["up", "tripped"],
    ["no_network", "stuck_connecting", "connected"],
]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def make_clips(directory: Path) -> None:
    """Write ``<lang>__<value>.wav`` clips and check each answer reads as its value."""
    x = RuleExtractor()
    for lang, answers in ANSWERS.items():
        for value, text in answers.items():
            outcomes = next(o for o in OUTCOME_SETS if value in o)
            got = x.extract_sync(text, outcomes).outcome
            if got != value:
                raise SystemExit(f"clip text {text!r} reads as {got}, not {value}")
            (directory / f"{lang}__{value}.wav").write_bytes(gnani_emulator.encode_clip(text))


def reset_database(database: str) -> str:
    # The load test downgrades this database to base: it must be listed in PRAMANA_DB_NAMES.
    db_guard.require_listed_database(database)
    dev_db.run(
        dev_db.pg_bin("createdb"),
        "-h",
        "localhost",
        "-p",
        str(dev_db.PORT),
        "-U",
        dev_db.USER,
        database,
        check=False,
    )
    url = f"postgresql+asyncpg://{dev_db.USER}@localhost:{dev_db.PORT}/{database}"
    from alembic import command
    from alembic.config import Config

    core_dir = ROOT / "services" / "core"
    cfg = Config(str(core_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(core_dir / "alembic"))
    cfg.attributes["url"] = url
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    return url


def working_set_mb(pid: int) -> float | None:
    """Resident memory of a process, without third-party packages."""
    if sys.platform == "win32":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        try:
            kb = out.strip().split('","')[-1].strip('"').replace(",", "").replace(" K", "")
            return int(kb) / 1024
        except (ValueError, IndexError):
            return None
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024
    except OSError:
        return None
    return None


def memory_slope_mb_per_min(samples: list[tuple[float, float]]) -> float | None:
    """Least-squares RSS slope over the steady half of elapsed-time samples."""
    if len(samples) < 4:
        return None
    steady = samples[len(samples) // 2 :]
    times = [point[0] / 60.0 for point in steady]
    values = [point[1] for point in steady]
    mean_time = sum(times) / len(times)
    mean_value = sum(values) / len(values)
    denominator = sum((value - mean_time) ** 2 for value in times)
    if denominator == 0:
        return None
    return (
        sum(
            (time - mean_time) * (value - mean_value)
            for time, value in zip(times, values, strict=True)
        )
        / denominator
    )


def memory_growth_gate(
    core: list[tuple[float, float]],
    sim: list[tuple[float, float]],
    *,
    limit_mb_per_min: float,
) -> bool:
    """Require enough samples and a bounded steady-state RSS slope for both services."""
    slopes = [memory_slope_mb_per_min(samples) for samples in (core, sim)]
    return all(slope is not None and slope <= limit_mb_per_min for slope in slopes)


def listener_pid(port: int) -> int | None:
    """The process listening on ``port``. On Windows a venv's python.exe is a launcher that
    starts the real interpreter as a child, so the launched pid is not the server's."""
    if sys.platform != "win32":
        return None
    out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(f":{port}") and parts[3] == "LISTENING":
            return int(parts[4])
    return None


def stop(proc: subprocess.Popen[bytes]) -> None:
    """Stop a server and everything it started (the venv launcher's child too)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.terminate()
    with contextlib.suppress(subprocess.TimeoutExpired):
        proc.wait(10)


def wait_ready(url: str, timeout: float = 60) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with contextlib.suppress(httpx.HTTPError):
            if httpx.get(url, timeout=2).status_code == 200:
                return
        time.sleep(0.3)
    raise SystemExit(f"{url} did not become ready")


async def one_run(core: str, sim: str, clips: Path, n: int) -> dict[str, Any]:
    import voice_bot_run

    args = argparse.Namespace(
        core=core,
        sim=sim,
        clips=str(clips),
        play=True,  # question audio is streamed to every call, as on a phone
        timeout=600.0,
        human=None,
        attach=None,
        public_url="http://localhost:3002",
        parallel=3,
    )
    run = voice_bot_run.Run(args)
    out = io.StringIO()
    error = None
    started = time.time()
    try:
        with contextlib.redirect_stdout(out):
            code = await run.main()
    except Exception as exc:  # a dropped socket or any failure is a result, not a crash
        code, error = 1, f"{type(exc).__name__}: {exc}"
    log = out.getvalue()
    final = next((ln for ln in log.splitlines() if ln.startswith("FINAL")), "")
    return {
        "run": n,
        "investigation": run.inv.get("id"),
        "ok": code == 0,
        "error": error,
        "seconds": round(time.time() - started, 1),
        "voice_answers": run.voice_answers,
        "most_in_flight": run.most_at_once,
        "withdrawn": run.withdrawn,
        "fatal_call_errors": [ln.strip() for ln in log.splitlines() if ": error " in ln],
        "correct": "decision correct = True" in log,
        "replay_identical": "replay identical: True" in log,
        "final": final,
    }


async def drive(
    args: argparse.Namespace, core: str, sim: str, clips: Path, pid: int, sim_pid: int
) -> dict[str, Any]:
    deadline = time.time() + args.minutes * 60
    runs: list[dict[str, Any]] = []
    core_memory: list[tuple[float, float]] = []
    sim_memory: list[tuple[float, float]] = []
    governor: list[dict[str, Any]] = []
    t0 = time.time()
    stop = asyncio.Event()

    async def sample(sim_pid: int) -> None:
        async with httpx.AsyncClient(
            base_url=core, headers=voice_bot_run_headers(), timeout=10
        ) as c:
            while not stop.is_set():
                elapsed = round(time.time() - t0, 1)
                core_mb = working_set_mb(pid)
                sim_mb = working_set_mb(sim_pid)
                if core_mb is not None:
                    core_memory.append((elapsed, round(core_mb, 1)))
                if sim_mb is not None:
                    sim_memory.append((elapsed, round(sim_mb, 1)))
                with contextlib.suppress(httpx.HTTPError):
                    governor.append((await c.get("/v1/voice/usage")).json())
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(stop.wait(), args.sample_s)

    sampler = asyncio.create_task(sample(sim_pid))
    n = 0
    while n < args.investigations if args.investigations is not None else time.time() < deadline:
        n += 1
        r = await one_run(core, sim, clips, n)
        runs.append(r)
        print(
            f"run {n}: {'ok' if r['ok'] else 'FAILED'} in {r['seconds']} s, "
            f"{r['voice_answers']} voice answers, {r['most_in_flight']} in flight at most"
            + (f", error {r['error']}" if r["error"] else ""),
            flush=True,
        )
    stop.set()
    await sampler
    return {
        "runs": runs,
        "core_memory_mb": core_memory,
        "sim_memory_mb": sim_memory,
        "governor": governor,
        "seconds": time.time() - t0,
    }


def voice_bot_run_headers() -> dict[str, str]:
    return {"X-Automation-Key": os.environ["CORE_AUTOMATION_KEY"]}


def report(
    out: Path, result: dict[str, Any], emulator: dict[str, Any], args: argparse.Namespace
) -> bool:
    runs = result["runs"]
    core_mem = [m for _, m in result["core_memory_mb"]]
    sim_mem = [m for _, m in result["sim_memory_mb"]]
    half = len(core_mem) // 2
    core_slope = memory_slope_mb_per_min(result["core_memory_mb"])
    sim_slope = memory_slope_mb_per_min(result["sim_memory_mb"])
    memory_gate = (
        None
        if args.investigations is not None
        else memory_growth_gate(
            result["core_memory_mb"], result["sim_memory_mb"], limit_mb_per_min=0.5
        )
    )
    max_streams = max((g.get("open_streams", 0) for g in result["governor"]), default=None)
    cap = next((g["limits"]["max_streams"] for g in result["governor"] if "limits" in g), None)
    ok_runs = sum(r["ok"] for r in runs)
    summary = {
        "git_sha": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
        ).stdout.strip(),
        "gnani": "emulated (scripts/gnani_emulator.py); no Gnani service was called",
        "minutes": args.minutes if args.investigations is None else None,
        "investigations_requested": args.investigations,
        "runs": len(runs),
        "runs_ok": ok_runs,
        "runs_correct": sum(r["correct"] for r in runs),
        "replay_identical": sum(r["replay_identical"] for r in runs),
        "voice_answers": sum(r["voice_answers"] for r in runs),
        "most_questions_in_flight": max((r["most_in_flight"] for r in runs), default=0),
        "withdrawn": sum(r["withdrawn"] for r in runs),
        "call_errors": [e for r in runs for e in r["fatal_call_errors"]]
        + [r["error"] for r in runs if r["error"]],
        "recognizer_sessions": emulator["streams_total"],
        "recognizer_sessions_at_once_max": emulator["streams_max"],
        "recognizer_sessions_open_at_end": emulator["streams_now"],
        "sessions_ended_abnormally_by_core": emulator["client_dropped"],
        "rest_second_decodes": emulator["rest_stt"],
        "tts_streams": emulator["tts_sse"],
        "governor_stream_cap": cap,
        "governor_streams_in_use_max_sampled": max_streams,
        "core_memory_mb_first": core_mem[0] if core_mem else None,
        "core_memory_mb_last": core_mem[-1] if core_mem else None,
        "core_memory_mb_max": max(core_mem) if core_mem else None,
        "core_memory_mb_mean_first_half": round(sum(core_mem[:half]) / half, 1) if half else None,
        "core_memory_mb_mean_second_half": (
            round(sum(core_mem[half:]) / (len(core_mem) - half), 1) if core_mem[half:] else None
        ),
        "sim_memory_mb_first": sim_mem[0] if sim_mem else None,
        "sim_memory_mb_last": sim_mem[-1] if sim_mem else None,
        "sim_memory_mb_max": max(sim_mem) if sim_mem else None,
        "core_memory_slope_mb_per_min": core_slope,
        "sim_memory_slope_mb_per_min": sim_slope,
        "memory_growth_limit_mb_per_min": 0.5,
        "memory_growth_gate": memory_gate,
        "core_memory_samples": result["core_memory_mb"],
        "sim_memory_samples": result["sim_memory_mb"],
        "per_run": runs,
    }
    passed = (
        bool(runs)
        and ok_runs == len(runs)
        and not summary["call_errors"]
        and emulator["streams_now"] == 0
        and (cap is None or emulator["streams_max"] <= cap)
        and (memory_gate is None or memory_gate)
    )
    summary["passed"] = passed
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    duration = (
        f"Exactly {args.investigations} full investigation"
        f"{'s' if args.investigations != 1 else ''}, three"
        if args.investigations is not None
        else f"{args.minutes} minutes of back-to-back investigations, three"
    )
    lines = [
        "# Load test report (generated; do not edit)",
        "",
        f"Commit `{summary['git_sha']}`. Gnani was **emulated**; the simulator, core,",
        "PostgreSQL, call sockets, recognizer sessions, extractor, engine, approvals and",
        f"verification were real. {duration}",
        "participants each, up to three questions in flight, question audio streamed to every",
        "call.",
        "",
        "| Measure | Value |",
        "|---|---|",
        f"| Investigations run | {len(runs)} |",
        f"| Verified, correct on reveal | {summary['runs_correct']} of {len(runs)} |",
        f"| Replay byte-identical | {summary['replay_identical']} of {len(runs)} |",
        f"| Runs that ended as expected | {ok_runs} of {len(runs)} |",
        f"| Call socket errors | {len(summary['call_errors'])} |",
        f"| Voice answers | {summary['voice_answers']} |",
        f"| Most questions in flight at once | {summary['most_questions_in_flight']} |",
        f"| Questions withdrawn | {summary['withdrawn']} |",
        "| Recognizer sessions (total / most at once / open at the end) | "
        f"{emulator['streams_total']} / {emulator['streams_max']} / {emulator['streams_now']} |",
        f"| Governor stream cap | {cap} |",
        f"| Second decodes (REST) | {emulator['rest_stt']} |",
        f"| Streamed question audio | {emulator['tts_sse']} |",
        "| Core memory MB (first / max / last) | "
        f"{summary['core_memory_mb_first']} / {summary['core_memory_mb_max']} / "
        f"{summary['core_memory_mb_last']} |",
        "| Core memory MB (mean, first half / second half) | "
        f"{summary['core_memory_mb_mean_first_half']} / "
        f"{summary['core_memory_mb_mean_second_half']} |",
        f"| Core RSS slope after warm-up (MB/min) | {core_slope} |",
        f"| Simulator RSS slope after warm-up (MB/min) | {sim_slope} |",
        (
            "| Memory growth gate (<= 0.5 MB/min each) | not sampled for fixed-count run |"
            if memory_gate is None
            else (
                f"| Memory growth gate (<= 0.5 MB/min each) | "
                f"{'passed' if memory_gate else 'FAILED'} |"
            )
        ),
        "",
        f"**Result: {'passed' if passed else 'FAILED'}.**",
    ]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return passed


def _event_time(event: dict[str, Any]) -> float | None:
    value = event.get("timestamp")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def latency_samples(log_path: Path) -> dict[str, list[float]]:
    """Build privacy-safe per-hop durations from structured voice_hop log events."""
    traces: dict[str, dict[str, dict[str, Any]]] = {}
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") != "voice_hop" or not isinstance(event.get("trace_id"), str):
            continue
        hop = event.get("hop")
        if isinstance(hop, str):
            traces.setdefault(event["trace_id"], {})[hop] = event

    names = (
        "capture_duration",
        "capture_to_proxy_commit",
        "upstream_connect",
        "commit_to_transcript",
        "extraction",
        "answer_to_next_question_tts",
        "tts_to_playback",
        "turn_total",
    )
    samples = {name: [] for name in names}
    for events in traces.values():
        capture = events.get("capture_end")
        commit = events.get("proxy_commit_received")
        if capture and isinstance(capture.get("capture_duration_ms"), (int, float)):
            samples["capture_duration"].append(float(capture["capture_duration_ms"]))
        capture_at = _event_time(capture or {})
        commit_at = _event_time(commit or {})
        if capture_at is not None and commit_at is not None:
            samples["capture_to_proxy_commit"].append(max(0.0, (commit_at - capture_at) * 1000))
        connected = events.get("upstream_connected")
        if connected and isinstance(connected.get("duration_ms"), (int, float)):
            samples["upstream_connect"].append(float(connected["duration_ms"]))
        transcript = events.get("transcript_received")
        if transcript and isinstance(transcript.get("since_commit_ms"), (int, float)):
            samples["commit_to_transcript"].append(float(transcript["since_commit_ms"]))
        extraction = events.get("extraction_complete")
        if extraction:
            if isinstance(extraction.get("duration_ms"), (int, float)):
                samples["extraction"].append(float(extraction["duration_ms"]))
            if isinstance(extraction.get("total_turn_ms"), (int, float)):
                samples["turn_total"].append(float(extraction["total_turn_ms"]))
        next_tts = events.get("next_question_tts_first_byte")
        extraction_at = _event_time(extraction or {})
        next_tts_at = _event_time(next_tts or {})
        if extraction_at is not None and next_tts_at is not None:
            samples["answer_to_next_question_tts"].append(
                max(0.0, (next_tts_at - extraction_at) * 1000)
            )
        tts = events.get("tts_first_byte")
        playback = events.get("playback_started")
        tts_at = _event_time(tts or {})
        playback_at = _event_time(playback or {})
        if tts_at is not None and playback_at is not None:
            samples["tts_to_playback"].append(max(0.0, (playback_at - tts_at) * 1000))
    return samples


def _percentile(values: list[float], percentile: int) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile / 100 * len(ordered)) - 1)]


def write_latency_report(
    path: Path, log_path: Path, emulator: dict[str, Any], args: argparse.Namespace
) -> None:
    samples = latency_samples(log_path)
    total_turn_ms = sum(samples["turn_total"])
    synthetic_capture_ms = sum(samples["capture_duration"])
    non_capture_turn_ms = max(0.0, total_turn_ms - synthetic_capture_ms)
    provider_placeholder_ms = (
        int(emulator["transcripts"]) * gnani_emulator.STT_PLACEHOLDER_DELAY_S * 1000
        + int(emulator["tts_sse"])
        * gnani_emulator.TTS_CHUNKS_PER_REQUEST
        * gnani_emulator.TTS_CHUNK_PLACEHOLDER_DELAY_S
        * 1000
    )
    capture_share_total = synthetic_capture_ms / total_turn_ms if total_turn_ms else None
    provider_share_total = provider_placeholder_ms / total_turn_ms if total_turn_ms else None
    provider_share_non_capture = (
        min(1.0, provider_placeholder_ms / non_capture_turn_ms) if non_capture_turn_ms else None
    )
    local_share_non_capture = (
        1.0 - provider_share_non_capture if provider_share_non_capture is not None else None
    )
    labels = {
        "capture_duration": "Client capture duration (synthetic fixture clips)",
        "capture_to_proxy_commit": "Capture-end frame to proxy commit",
        "upstream_connect": "Proxy upstream WebSocket connect",
        "commit_to_transcript": "Commit to transcript at proxy",
        "extraction": "Extraction and engine update",
        "answer_to_next_question_tts": "Answer extraction to next question TTS first byte",
        "tts_to_playback": "TTS first byte to browser playback start",
        "turn_total": "Total server turn time",
    }
    lines = [
        "# Voice latency waterfall: emulator, not Gnani performance",
        "",
        f"Generated by scripts/load_test.py with exactly {args.investigations} full "
        f"investigation{'s' if args.investigations != 1 else ''} on "
        f"{time.strftime('%Y-%m-%d', time.gmtime())}.",
        "",
        "**This is emulator, not Gnani performance.** The harness used synthetic answer clips and "
        "silent synthetic question audio. It verifies the integration path and local code timing; "
        "it measures no provider quality or latency.",
        "",
        f"The run completed {args.investigations} full investigation"
        f"{'s' if args.investigations != 1 else ''}. The bot capture-end "
        "duration comes from its synthetic PCM fixture, not a physical microphone. Browser "
        "clients send the same capture-end control frame.",
        "",
        "| Hop | Samples | p50 ms | p95 ms |",
        "|---|---:|---:|---:|",
    ]
    for key, label in labels.items():
        values = samples[key]
        if values:
            lines.append(
                f"| {label} | {len(values)} | {_percentile(values, 50):.1f} | "
                f"{_percentile(values, 95):.1f} |"
            )
        else:
            lines.append(f"| {label} | 0 | n/a | n/a |")
    lines.extend(
        [
            "",
            "## Time ownership estimate",
            "",
            f"- Fixed provider placeholder delays: {provider_placeholder_ms:.0f} ms summed across "
            f"{emulator['transcripts']} realtime STT transcripts and {emulator['tts_sse']} TTS "
            "streams. The emulator injects 50 ms per STT transcript and 50 ms before each of "
            "three TTS chunks.",
            f"- Summed measured server turn time: {total_turn_ms:.0f} ms.",
            f"- Synthetic answer audio transmission: {synthetic_capture_ms:.0f} ms, "
            + (
                f"{capture_share_total * 100:.1f}% of measured turn time. "
                if capture_share_total is not None
                else "n/a of measured turn time because no turn samples were recorded. "
            )
            + (
                "This is the test bot sending fixture audio at real-time cadence, "
                "not Pramana code or Gnani."
            ),
            "- Provider placeholders: "
            + (
                f"{provider_share_total * 100:.1f}% of total measured turn time, and "
                if provider_share_total is not None
                else "n/a of total measured turn time because no turn samples were recorded, and "
            )
            + (
                f"{provider_share_non_capture * 100:.1f}% after excluding synthetic answer audio."
                if provider_share_non_capture is not None
                else "n/a after excluding synthetic answer audio because no time remains."
            ),
            "- Remaining non-capture time: "
            + (
                f"{local_share_non_capture * 100:.1f}% after excluding provider placeholders. "
                "It includes Pramana code, local transport and host scheduling, so it is not a "
                "pure application-code measurement."
                if local_share_non_capture is not None
                else "n/a because the sample contains no non-capture turn time."
            ),
            "",
            "These shares compare summed per-turn durations, not wall-clock investigation time. "
            "The synthetic audio duration is recorded from capture_end and removed before the "
            "provider-versus-local split. Fixed emulator sleeps define the provider placeholder "
            "portion; HTTP/WebSocket scheduling and local host timing remain in local time. REST "
            "second-decode responses have no artificial delay. A live Gnani rehearsal and "
            "consented human speech are still needed to measure end-to-end voice quality or "
            "latency.",
            "",
            "Re-run scripts/load_test.py with --investigations N and --latency-report to refresh.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=10.0)
    ap.add_argument("--investigations", type=int, help="run exactly N full investigations")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--database", default=os.environ.get("E2E_DATABASE"))
    ap.add_argument("--latency-report", type=Path)
    ap.add_argument("--sample-s", type=float, default=5.0)
    ap.add_argument(
        "--fault",
        choices=("none", "drop", "429", "5xx", "slow", "partial", "malformed", "noise"),
        default="none",
    )
    ap.add_argument("--noise-seed", type=int, default=7)
    args = ap.parse_args()

    if args.investigations is not None and args.investigations < 1:
        ap.error("--investigations must be at least 1")
    if args.latency_report is not None and args.investigations is None:
        ap.error("--latency-report requires --investigations")
    if not args.database:
        ap.error("set E2E_DATABASE from this worktree .env or pass --database")
    url = reset_database(args.database)
    signing = generate_private_key_b64()
    operator_key, automation_key = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    emu_port, sim_port, core_port = free_port(), free_port(), free_port()
    stats, emulator = gnani_emulator.serve_in_thread(
        emu_port, fault=args.fault, noise_seed=args.noise_seed
    )
    env = {
        **os.environ,
        "PRAMANA_MODE": "dev",
        "DATABASE_URL": url,
        "SIM_URL": f"http://127.0.0.1:{sim_port}",
        "SIM_OPERATOR_KEY": operator_key,
        "PARTICIPANT_SIGNING_KEY": signing,
        "SIM_PARTICIPANT_PUBLIC_KEY": public_key_b64(private_key_from_b64(signing)),
        "SIM_ORACLE_KEY": "",
        "GNANI_API_KEY": "emulated-not-a-key",
        "GNANI_BASE_URL": f"http://127.0.0.1:{emu_port}",
        "GNANI_PROTOCOL_EMULATOR": "true",
        "VOICE_DAILY_BUDGET_INR": "100000",  # emulated: nothing is spent
        "CORE_AUTOMATION_KEY": automation_key,
        "LLM_EXTRACTOR_PROVIDER": "none",
        "TTS_CACHE_DIR": "",
        "LOG_LEVEL": "INFO" if args.latency_report else "WARNING",
        "LOG_JSON": "true",
        "PYTHONIOENCODING": "utf-8",
    }
    os.environ["CORE_AUTOMATION_KEY"] = automation_key
    logs_tmp = tempfile.TemporaryDirectory(prefix="pramana-load-")
    logs = Path(logs_tmp.name)
    procs: list[subprocess.Popen[bytes]] = []
    files = contextlib.ExitStack()
    try:
        procs.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "pramana_sim.app:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(sim_port),
                    "--log-level",
                    "warning",
                ],
                env={**env, "PRAMANA_TRACE_NAME": "sim"},
                cwd=ROOT,
                stdout=files.enter_context(open(logs / "sim.log", "w")),  # noqa: SIM115
                stderr=subprocess.STDOUT,
            )
        )
        procs.append(
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "pramana_core.main:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(core_port),
                    "--log-level",
                    "warning",
                ],
                env={**env, "PRAMANA_TRACE_NAME": "core"},
                cwd=ROOT,
                stdout=files.enter_context(open(logs / "core.log", "w")),  # noqa: SIM115
                stderr=subprocess.STDOUT,
            )
        )
        wait_ready(f"http://127.0.0.1:{sim_port}/health")
        wait_ready(f"http://127.0.0.1:{core_port}/health")
        sim_pid = listener_pid(sim_port) or procs[0].pid
        with tempfile.TemporaryDirectory(prefix="pramana-clips-") as clips:
            make_clips(Path(clips))
            result = asyncio.run(
                drive(
                    args,
                    f"http://127.0.0.1:{core_port}",
                    f"http://127.0.0.1:{sim_port}",
                    Path(clips),
                    listener_pid(core_port) or procs[1].pid,
                    sim_pid,
                )
            )
        for process in procs:
            stop(process)
        procs.clear()
        files.close()
        if args.latency_report is not None:
            write_latency_report(args.latency_report, logs / "core.log", stats.as_dict(), args)
        ok = report(args.out, result, stats.as_dict(), args)
        return 0 if ok else 1
    finally:
        for p in procs:
            stop(p)
        files.close()
        gnani_emulator.stop_in_thread(emulator)
        logs_tmp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
