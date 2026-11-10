"""Record the local, simulated S1 demo with Playwright's bundled Chromium."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
DOCS = ROOT / "docs" / "demo-video"
DEFAULT_OUTPUT = Path(r"C:\Dev\Pramana-AI\.claude\worktrees\nov10-polish\.cache\nov10\out\B7")
MILESTONES_FOR_SHORT = (
    "first_time_operator",
    "question_choice",
    "participant_answer",
    "decision",
    "approval_requested",
    "approval_decided",
    "repair_reported",
    "verification_complete",
    "reveal",
    "replay",
)
FULL_CUT_SECONDS = 150.0
REVIEW_FRAME_DELAY_SECONDS = 3.0


class RecordingError(RuntimeError):
    pass


def _local_config() -> dict[str, str]:
    path = ROOT / ".env"
    if not path.is_file():
        raise RecordingError("The worktree .env file is required for its database names and ports.")
    raw = {key: value for key, value in dotenv_values(path).items() if value is not None}
    names = [item.strip() for item in raw.get("PRAMANA_DB_NAMES", "").split(",") if item.strip()]
    database = raw.get("E2E_DATABASE", "").strip()
    if not names or database not in names or not database.endswith("_e2e"):
        raise RecordingError(
            "The worktree .env must list its dedicated E2E_DATABASE in PRAMANA_DB_NAMES."
        )
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", database):
        raise RecordingError("The worktree E2E database name is not valid.")
    database_url = raw.get("DATABASE_URL", "")
    url_port = urlsplit(database_url).port if database_url else None
    db_port = int(raw.get("PRAMANA_DB_PORT") or url_port or 5433)
    values = {
        "PRAMANA_DB_NAMES": ",".join(names),
        "PRAMANA_DB_PORT": str(db_port),
        "E2E_DATABASE": database,
    }
    for key in ("E2E_WEB_PORT", "E2E_CORE_PORT", "E2E_SIM_PORT", "E2E_OIDC_PORT"):
        try:
            port = int(raw[key])
        except (KeyError, ValueError) as exc:
            raise RecordingError(f"The worktree .env must define {key}.") from exc
        if not 1 <= port <= 65535:
            raise RecordingError(f"The worktree .env value for {key} is out of range.")
        values[key] = str(port)
    ports = [
        int(values[key])
        for key in ("E2E_WEB_PORT", "E2E_CORE_PORT", "E2E_SIM_PORT", "E2E_OIDC_PORT")
    ]
    ports.append(int(values["E2E_OIDC_PORT"]) + 1)
    if len(set(ports)) != len(ports) or any(port > 65535 for port in ports):
        raise RecordingError("The worktree .env ports overlap, or leave no port for the emulator.")
    return values


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _run(command: list[str], *, cwd: Path, env: dict[str, str], timeout: int) -> None:
    print("$ " + subprocess.list2cmdline(command), flush=True)
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    process = subprocess.Popen(command, cwd=cwd, env=env, **kwargs)
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True,
                check=False,
            )
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        raise RecordingError(f"Command exceeded its {timeout}-second timeout.") from exc
    if returncode:
        raise RecordingError(f"Command failed with exit code {returncode}.")


def _ffprobe(video: Path) -> tuple[float, int, int]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RecordingError("ffprobe is required to verify output durations and dimensions.")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=width,height",
            "-of",
            "json",
            str(video),
        ],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    if result.returncode:
        raise RecordingError("ffprobe could not read " + str(video))
    data = json.loads(result.stdout)
    stream = next((item for item in data.get("streams", []) if "width" in item), None)
    if stream is None:
        raise RecordingError("Video has no readable image stream: " + str(video))
    return float(data["format"]["duration"]), int(stream["width"]), int(stream["height"])


def _timestamp(milliseconds: int) -> str:
    milliseconds = max(0, milliseconds)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02}:{minutes:02}:{seconds:02}.{millis:03}"


def _write_full_captions(
    timeline: dict[str, Any],
    duration_ms: int,
    path: Path,
    *,
    time_scale: float = 1.0,
    compression_label: str | None = None,
) -> None:
    moments = timeline["milestones"]
    lines = ["WEBVTT", ""]
    cue_id = 1
    if compression_label:
        lines.extend(
            [
                "NOTE " + compression_label,
                "",
                str(cue_id),
                _timestamp(0) + " --> " + _timestamp(min(duration_ms, 6_000)),
                compression_label,
                "",
            ]
        )
        cue_id += 1
    for index, moment in enumerate(moments):
        start = int(int(moment["elapsed_ms"]) * time_scale)
        later = [
            int(int(item["elapsed_ms"]) * time_scale)
            for item in moments[index + 1 :]
            if int(int(item["elapsed_ms"]) * time_scale) > start
        ]
        end = min(duration_ms, start + 6_000, min(later) if later else duration_ms)
        if end <= start:
            end = min(duration_ms, start + 1_500)
        lines.extend(
            [
                str(cue_id),
                _timestamp(start) + " --> " + _timestamp(end),
                str(moment["caption"]),
                "",
            ]
        )
        cue_id += 1
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def _write_short_captions(moments: list[dict[str, Any]], path: Path) -> None:
    lines = ["WEBVTT", ""]
    for index, moment in enumerate(moments):
        start = index * 6_000
        lines.extend(
            [
                str(index + 1),
                _timestamp(start) + " --> " + _timestamp(start + 6_000),
                (
                    "Time-compressed highlights: " + str(moment["caption"])
                    if index == 0
                    else str(moment["caption"])
                ),
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def _find_cut_moments(timeline: dict[str, Any]) -> list[dict[str, Any]]:
    moments = timeline["milestones"]
    selected: list[dict[str, Any]] = []
    for name in MILESTONES_FOR_SHORT:
        match = next((item for item in moments if item["name"] == name), None)
        if match is None:
            raise RecordingError("The actual event timeline is missing milestone " + name + ".")
        selected.append(match)
    return selected


def _band_height(width: int) -> int:
    return 44 if width > 1_000 else 30


def _fit_below_band(width: int, height: int) -> str:
    """Scale the source into the frame below a reserved top band, so the app is never covered."""
    band = _band_height(width)
    return f"scale={width}:{height - band}:flags=lanczos,pad={width}:{height}:0:{band}"


def _top_band_label(text: str, width: int) -> str:
    """Write the compression note into the reserved top band. The band matches the simulation
    disclosure bar at the bottom of every frame."""
    band = _band_height(width)
    font_size = 26 if width > 1_000 else 14
    return (
        f"drawbox=x=0:y=0:w=iw:h={band}:color=0x171717:t=fill,"
        "drawtext=fontfile='C\\:/Windows/Fonts/arial.ttf':"
        f"text='{text}':fontcolor=white:fontsize={font_size}:"
        f"x=(w-text_w)/2:y=({band}-text_h)/2"
    )


def _make_short_cut(
    source: Path, target: Path, moments: list[dict[str, Any]], size: tuple[int, int]
) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RecordingError("ffmpeg is required to make the 60-second cut.")
    duration, _, _ = _ffprobe(source)
    if duration < 60:
        raise RecordingError("The full recording is shorter than 60 seconds: " + str(source))
    width, height = size
    filters: list[str] = []
    labels: list[str] = []
    for index, moment in enumerate(moments):
        stamp = float(moment["elapsed_ms"]) / 1_000
        if index == 0:
            start = 0.0
        elif width <= 400 and moment["name"] == "question_choice":
            start = stamp + 2.0
        else:
            start = max(0.0, stamp - 2.0)
        if start + 6.0 > duration:
            start = max(0.0, duration - 6.0)
        label = f"v{index}"
        labels.append("[" + label + "]")
        filters.append(
            f"[0:v]trim=start={start:.3f}:duration=6,setpts=PTS-STARTPTS,"
            f"fps=30,{_fit_below_band(width, height)},"
            f"tpad=stop_mode=clone:stop_duration=1,trim=duration=6[{label}]"
        )
    filters.append(
        "".join(labels)
        + f"concat=n={len(moments)}:v=1:a=0,"
        + _top_band_label("Time-compressed highlights", width)
        + "[outv]"
    )
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[outv]",
            "-an",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-t",
            "60",
            "-movflags",
            "+faststart",
            str(target),
        ],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    if result.returncode:
        raise RecordingError(
            "ffmpeg could not create " + str(target) + ": " + result.stderr[-1200:]
        )


def _make_full_cut(
    source: Path, target: Path, source_duration: float, size: tuple[int, int]
) -> float:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RecordingError("ffmpeg is required to make the 2.5-minute full cut.")
    if source_duration <= FULL_CUT_SECONDS:
        raise RecordingError("The paced source must exceed the 150-second full-cut target.")
    speed = source_duration / FULL_CUT_SECONDS
    width, height = size
    result = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-vf",
            f"setpts=PTS/{speed:.8f},fps=30,{_fit_below_band(width, height)},"
            + _top_band_label(f"Time-compressed {speed:.2f}x", width),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-t",
            str(FULL_CUT_SECONDS),
            "-movflags",
            "+faststart",
            str(target),
        ],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    if result.returncode:
        raise RecordingError(
            "ffmpeg could not create " + str(target) + ": " + result.stderr[-1200:]
        )
    return speed


def _extract_review_frames(output: Path, timeline: dict[str, Any], videos: dict[str, Path]) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RecordingError("ffmpeg is required to extract review frames.")
    directory = output / "frames"
    directory.mkdir(parents=True, exist_ok=True)
    wanted = (
        "question_choice",
        "decision",
        "approval_requested",
        "approval_decided",
        "repair_reported",
        "verification_complete",
        "reveal",
        "replay",
    )
    for name in wanted:
        moment = next((item for item in timeline["milestones"] if item["name"] == name), None)
        if moment is None:
            continue
        delay = 1.3 if name == "reveal" else REVIEW_FRAME_DELAY_SECONDS
        milestone_seconds = max(
            0.0,
            float(moment["elapsed_ms"]) / 1_000 + delay,
        )
        for label, video in videos.items():
            source_duration, _, _ = _ffprobe(video)
            seconds = min(milestone_seconds, max(0.0, source_duration - 0.1))
            target = directory / f"{label}-{name}.png"
            result = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{seconds:.3f}",
                    "-i",
                    str(video),
                    "-frames:v",
                    "1",
                    str(target),
                ],
                capture_output=True,
                check=False,
            )
            if result.returncode:
                raise RecordingError("ffmpeg could not extract review frame " + str(target))


def _write_shot_list(
    timeline: dict[str, Any],
    source_durations: dict[str, float],
    full_durations: dict[str, float],
    short_durations: dict[str, float],
    compression: dict[str, float],
    output: Path,
) -> None:
    lines = [
        "# B7 S1 recording shot list",
        "",
        (
            "Generated from the successful local S1 run in timeline.json. "
            "Captions come from observed UI actions or core events."
        ),
        "",
        "## Recordings",
        "",
        "| File | Resolution | Duration |",
        "|---|---:|---:|",
        (
            "| demo-s1-desktop-paced-source.webm | 1920 x 1080 | "
            f"{source_durations['desktop']:.2f} s |"
        ),
        (f"| demo-s1-phone-paced-source.webm | 390 x 844 | {source_durations['phone']:.2f} s |"),
        f"| demo-s1-desktop-full.mp4 | 1920 x 1080 | {full_durations['desktop']:.2f} s |",
        f"| demo-s1-phone-full.mp4 | 390 x 844 | {full_durations['phone']:.2f} s |",
        f"| demo-s1-desktop-60s.mp4 | 1920 x 1080 | {short_durations['desktop']:.2f} s |",
        f"| demo-s1-phone-60s.mp4 | 390 x 844 | {short_durations['phone']:.2f} s |",
        "",
        (
            f"The full cuts use {compression['desktop']:.2f}x desktop and "
            f"{compression['phone']:.2f}x phone playback. The 60-second cuts use "
            "excerpted shots. Both compressed formats carry an on-screen label."
        ),
        "",
        "## Observed shots",
        "",
        "| Time | Event | Caption source |",
        "|---:|---|---|",
    ]
    for moment in timeline["milestones"]:
        sequence = moment.get("event_seq")
        event = str(moment["event_type"]) + (f" #{sequence}" if sequence is not None else "")
        lines.append(
            f"| {float(moment['elapsed_ms']) / 1_000:.2f} s | {event} | {moment['caption']} |"
        )
    lines.extend(
        [
            "",
            (
                "The emulator returns silent WAV/PCM data and the browser recording has no "
                "real participant audio. The synthetic-audio disclosure remains visible "
                "throughout the paced sources and compressed cuts."
            ),
            "",
        ]
    )
    output.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def _prepare_env(values: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(values)
    env.pop("PW_CHANNEL", None)
    env["DEMO_VIDEO"] = "0"
    env["DEMO_FAST"] = "0"
    return env


def _record(args: argparse.Namespace) -> dict[str, Any]:
    values = _local_config()
    ports = [
        int(values[key])
        for key in ("E2E_WEB_PORT", "E2E_CORE_PORT", "E2E_SIM_PORT", "E2E_OIDC_PORT")
    ]
    ports.append(int(values["E2E_OIDC_PORT"]) + 1)
    busy = [port for port in ports if _port_in_use(port)]
    if busy:
        raise RecordingError("A local demo port is already in use: " + ", ".join(map(str, busy)))

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = _prepare_env(values)
    env["DEMO_VIDEO"] = "0" if args.no_video else "1"
    env["DEMO_FAST"] = "1" if args.fast else "0"
    if args.fast and not args.no_video:
        raise RecordingError("--fast requires --no-video so a rushed take is never published.")

    npm = shutil.which("npm")
    npx = shutil.which("npx")
    uv = shutil.which("uv")
    if not npm or not npx or not uv:
        raise RecordingError("npm, npx and uv must be available on PATH.")
    browser_package = WEB / "node_modules" / "@playwright" / "test" / "package.json"
    if not browser_package.is_file():
        _run([npm, "ci"], cwd=WEB, env=env, timeout=600)
    _run([npx, "playwright", "install", "chromium"], cwd=WEB, env=env, timeout=600)
    _run([uv, "run", "python", "scripts/dev_db.py", "start"], cwd=ROOT, env=env, timeout=180)

    cache = ROOT / ".cache"
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="b7-demo-", dir=cache) as temp:
        temporary = Path(temp)
        env["DEMO_RESULTS_DIR"] = str(temporary / "playwright-results")
        env["DEMO_TIMELINE_PATH"] = str(temporary / "timeline.json")
        env["DEMO_VIDEO_DIR"] = str(output)
        _run(
            [npx, "playwright", "test", "-c", "playwright.demo.config.ts"],
            cwd=WEB,
            env=env,
            timeout=1_200,
        )
        # The Next production build can add generated settings; this worktree started clean.
        subprocess.run(
            ["git", "checkout", "--", "apps/web/tsconfig.json"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
        timeline_path = temporary / "timeline.json"
        if not timeline_path.is_file():
            raise RecordingError("Playwright passed without writing the actual event timeline.")
        timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
        if timeline.get("scenario") != "S1" or timeline.get("replay_identical") is not True:
            raise RecordingError("The saved timeline did not prove a successful S1 replay.")
        (output / "timeline.json").write_text(
            json.dumps(timeline, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        result: dict[str, Any] = {
            "scenario": timeline["scenario"],
            "duration_seconds": round(timeline["duration_ms"] / 1_000, 2),
            "question_count": timeline["question_count"],
            "answer_count": timeline["answer_count"],
            "verification_status": timeline["verification_status"],
            "commitment_verified": timeline["commitment_verified"],
            "correct": timeline["correct"],
            "replay_identical": timeline["replay_identical"],
            "output_directory": str(output),
            "video_files": [],
        }
        if not args.no_video:
            if args.fast:
                raise RecordingError("Video mode cannot use --fast.")
            desktop = output / "demo-s1-desktop-paced-source.webm"
            phone = output / "demo-s1-phone-paced-source.webm"
            for video in (desktop, phone):
                if not video.is_file():
                    raise RecordingError("Playwright did not save " + str(video))
            desktop_duration, desktop_width, desktop_height = _ffprobe(desktop)
            phone_duration, phone_width, phone_height = _ffprobe(phone)
            if (desktop_width, desktop_height) != (1920, 1080):
                raise RecordingError(
                    f"Desktop recording is {desktop_width} x {desktop_height}; "
                    "expected 1920 x 1080."
                )
            if (phone_width, phone_height) != (390, 844):
                raise RecordingError(
                    f"Phone recording is {phone_width} x {phone_height}, expected 390 x 844."
                )
            desktop_full = output / "demo-s1-desktop-full.mp4"
            phone_full = output / "demo-s1-phone-full.mp4"
            desktop_speed = _make_full_cut(desktop, desktop_full, desktop_duration, (1920, 1080))
            phone_speed = _make_full_cut(phone, phone_full, phone_duration, (390, 844))
            desktop_full_duration, desktop_full_width, desktop_full_height = _ffprobe(desktop_full)
            phone_full_duration, phone_full_width, phone_full_height = _ffprobe(phone_full)
            for label, duration, dimensions, expected_dimensions in (
                (
                    "desktop full cut",
                    desktop_full_duration,
                    (desktop_full_width, desktop_full_height),
                    (1920, 1080),
                ),
                (
                    "phone full cut",
                    phone_full_duration,
                    (phone_full_width, phone_full_height),
                    (390, 844),
                ),
            ):
                if abs(duration - FULL_CUT_SECONDS) > 0.25:
                    raise RecordingError(f"The {label} is {duration:.2f} seconds.")
                if dimensions != expected_dimensions:
                    raise RecordingError(
                        f"The {label} is {dimensions[0]} x {dimensions[1]}, "
                        f"expected {expected_dimensions[0]} x {expected_dimensions[1]}"
                    )
            cut_moments = _find_cut_moments(timeline)
            desktop_cut = output / "demo-s1-desktop-60s.mp4"
            phone_cut = output / "demo-s1-phone-60s.mp4"
            _make_short_cut(desktop, desktop_cut, cut_moments, (1920, 1080))
            _make_short_cut(phone, phone_cut, cut_moments, (390, 844))
            full_captions = DOCS / "captions-en-full.vtt"
            source_captions = DOCS / "captions-en-source.vtt"
            short_captions = DOCS / "captions-en-60s.vtt"
            DOCS.mkdir(parents=True, exist_ok=True)
            duration_ms = int(max(desktop_duration, phone_duration) * 1_000)
            mean_source_duration = (desktop_duration + phone_duration) / 2
            compression = {
                "desktop": desktop_speed,
                "phone": phone_speed,
            }
            cut_scale = FULL_CUT_SECONDS / mean_source_duration
            compression_label = (
                "Time-compressed playback at "
                + f"{(desktop_speed + phone_speed) / 2:.2f}x; paced source actions are faster."
            )
            _write_full_captions(timeline, duration_ms, source_captions)
            _write_full_captions(
                timeline,
                int(FULL_CUT_SECONDS * 1_000),
                full_captions,
                time_scale=cut_scale,
                compression_label=compression_label,
            )
            _write_short_captions(cut_moments, short_captions)
            shutil.copy2(full_captions, output / full_captions.name)
            shutil.copy2(source_captions, output / source_captions.name)
            shutil.copy2(short_captions, output / short_captions.name)
            source_durations = {"desktop": desktop_duration, "phone": phone_duration}
            _extract_review_frames(output, timeline, {"desktop": desktop, "phone": phone})
            video_files: list[dict[str, Any]] = []
            for video, duration, width, height in (
                (desktop, desktop_duration, desktop_width, desktop_height),
                (phone, phone_duration, phone_width, phone_height),
                (
                    desktop_full,
                    desktop_full_duration,
                    desktop_full_width,
                    desktop_full_height,
                ),
                (phone_full, phone_full_duration, phone_full_width, phone_full_height),
            ):
                video_files.append(
                    {
                        "path": str(video),
                        "duration_seconds": round(duration, 2),
                        "width": width,
                        "height": height,
                    }
                )
            short_durations: dict[str, float] = {}
            for label, cut, expected_size in (
                ("desktop", desktop_cut, (1920, 1080)),
                ("phone", phone_cut, (390, 844)),
            ):
                duration, width, height = _ffprobe(cut)
                if abs(duration - 60.0) > 0.25:
                    raise RecordingError(f"The short cut is {duration:.2f} seconds: {cut}")
                if (width, height) != expected_size:
                    raise RecordingError(
                        f"The short cut is {width} x {height}, expected "
                        f"{expected_size[0]} x {expected_size[1]}"
                    )
                short_durations[label] = duration
                video_files.append(
                    {
                        "path": str(cut),
                        "duration_seconds": round(duration, 2),
                        "width": width,
                        "height": height,
                    }
                )
            result["video_files"] = video_files
            result["caption_files"] = [
                str(full_captions),
                str(source_captions),
                str(short_captions),
            ]
            result["source_recording_durations"] = source_durations
            result["full_cut_durations"] = {
                "desktop": desktop_full_duration,
                "phone": phone_full_duration,
            }
            result["time_compression"] = compression
            timeline["video_cuts"] = {
                "full_duration_seconds": FULL_CUT_SECONDS,
                "time_compression": compression,
                "short_duration_seconds": 60.0,
                "labelled": True,
            }
            timeline_text = json.dumps(timeline, ensure_ascii=False, indent=2) + "\n"
            (output / "timeline.json").write_text(
                timeline_text,
                encoding="utf-8",
                newline="\n",
            )
            shutil.copy2(output / "timeline.json", DOCS / "timeline.json")
            shot_list = DOCS / "shot-list.md"
            _write_shot_list(
                timeline,
                source_durations,
                result["full_cut_durations"],
                short_durations,
                compression,
                shot_list,
            )
            shutil.copy2(shot_list, output / shot_list.name)

        summary_path = output / "summary.json"
        summary_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fast", action="store_true", help="skip human pacing pauses")
    parser.add_argument("--no-video", action="store_true", help="run the same flow without video")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    if args.fast and not args.no_video:
        parser.error("--fast requires --no-video.")
    try:
        result = _record(args)
    except (RecordingError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAIL demo recording: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
