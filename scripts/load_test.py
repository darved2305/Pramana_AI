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
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
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

DATABASE = "pramana_load_pf"

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


def reset_database() -> str:
    # The load test downgrades this database to base: it must be listed in PRAMANA_DB_NAMES.
    db_guard.require_listed_database(DATABASE)
    dev_db.run(
        dev_db.pg_bin("createdb"),
        "-h",
        "localhost",
        "-p",
        str(dev_db.PORT),
        "-U",
        dev_db.USER,
        DATABASE,
        check=False,
    )
    url = f"postgresql+asyncpg://{dev_db.USER}@localhost:{dev_db.PORT}/{DATABASE}"
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
    while time.time() < deadline:
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
    memory_gate = memory_growth_gate(
        result["core_memory_mb"], result["sim_memory_mb"], limit_mb_per_min=0.5
    )
    max_streams = max((g.get("open_streams", 0) for g in result["governor"]), default=None)
    cap = next((g["limits"]["max_streams"] for g in result["governor"] if "limits" in g), None)
    ok_runs = sum(r["ok"] for r in runs)
    summary = {
        "git_sha": subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=ROOT
        ).stdout.strip(),
        "gnani": "emulated (scripts/gnani_emulator.py); no Gnani service was called",
        "minutes": args.minutes,
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
        and memory_gate
    )
    summary["passed"] = passed
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    lines = [
        "# Load test report (generated; do not edit)",
        "",
        f"Commit `{summary['git_sha']}`. Gnani was **emulated**; the simulator, core,",
        "PostgreSQL, call sockets, recognizer sessions, extractor, engine, approvals and",
        f"verification were real. {args.minutes} minutes of back-to-back investigations, three",
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
        f"| Memory growth gate (<= 0.5 MB/min each) | {'passed' if memory_gate else 'FAILED'} |",
        "",
        f"**Result: {'passed' if passed else 'FAILED'}.**",
    ]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return passed


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=10.0)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sample-s", type=float, default=5.0)
    args = ap.parse_args()

    url = reset_database()
    signing = generate_private_key_b64()
    operator_key, automation_key = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    emu_port, sim_port, core_port = free_port(), free_port(), free_port()
    stats, emulator = gnani_emulator.serve_in_thread(emu_port)
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
        "VOICE_DAILY_BUDGET_INR": "100000",  # emulated: nothing is spent
        "CORE_AUTOMATION_KEY": automation_key,
        "LLM_EXTRACTOR_PROVIDER": "none",
        "TTS_CACHE_DIR": "",
        "LOG_LEVEL": "WARNING",
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
        ok = report(args.out, result, stats.as_dict(), args)
        return 0 if ok else 1
    finally:
        for p in procs:
            stop(p)
        files.close()
        emulator.should_exit = True
        logs_tmp.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
