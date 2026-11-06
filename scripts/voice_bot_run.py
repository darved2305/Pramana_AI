"""A whole investigation by voice, played by three simulated participants (spends a few rupees).

Each bot takes its participant's call (``WS .../participants/{pid}/call``): it accepts the ring,
gives consent, and for every question walks where it is asked, reads only what the simulator
shows that participant, and speaks the matching pre-recorded clip as 16 kHz PCM in real time.
The real Gnani Prisma v3.0 transcribes it and the engine decides. The script then requests and
approves the repair, the electrician resets the breaker with the capability, the verification
questions are answered by voice the same way, and finally the reveal and the replay are checked.

Clips: ``<clips>/<lang>__<value>.wav`` (16 kHz mono PCM16), lang ``hi`` or ``mr``, one per
observable value (yes, no, on, off, green, amber, red, up, tripped, no_network,
stuck_connecting, connected). See docs/engineering/VOICE_SAMPLES.md for open-source voices.

It prints integration facts only. Under the Gnani EULA measured accuracy and latency stay out
of the repository.

With ``--parallel N`` (2 or 3) the engine asks up to N people at once (docs/adr/0011): the bots
then talk at the same time on their own calls, and a question another answer made pointless is
withdrawn (``question_withdrawn``) while its bot is waiting or speaking.

Usage: python scripts/voice_bot_run.py --clips <dir> [--core URL] [--sim URL] [--play]
       [--parallel N]
       python scripts/voice_bot_run.py --synthetic --core URL --sim URL --parallel 3
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import statistics
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import websockets
from core_auth import automation_headers
from voice_bot_common import (
    CLIP_LANG,
    DONE,
    FRAME,
    PEOPLE,
    CallSocketMetrics,
    encode_synthetic_pcm,
    join_segment,
    mine,
    pcm,
    transcript_for_value,
    waiting,
)


class Run:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.core = httpx.AsyncClient(base_url=args.core, headers=automation_headers(), timeout=60)
        self.sim = httpx.AsyncClient(base_url=args.sim, timeout=30)
        self.clips = Path(args.clips) if args.clips else None
        self.socket_event_log = Path(args.socket_events) if args.socket_events else None
        self.tokens: dict[str, dict[str, str]] = {}
        self.inv: dict[str, Any] = {}
        self.log: list[str] = []
        self.voice_answers = 0
        self.stt_streams_opened = 0
        # Latency as the caller experiences it (private: printed, never committed).
        self.t_eos: dict[str, float] = {}
        """Per call: when the answer's voice ended (end of the clip, before the silence)."""
        self.t_answer: dict[str, float] = {}
        self.stt_ms: list[float] = []
        self.answer_ms: list[float] = []
        self.next_ms: list[float] = []
        self.tasks: set[asyncio.Task[None]] = set()
        self.task_errors: list[BaseException] = []
        self.observe_locks: dict[str, asyncio.Lock] = {}
        self.location_by_scenario: dict[str, str] = {}
        self.last_clip: dict[str, bytes] = {}
        self.call_closes: list[dict[str, Any]] = []
        self.call_metrics = CallSocketMetrics()
        self.withdrawn = 0
        self.most_at_once = 0
        self.idle_heartbeats = 0
        self.barge_ins = 0
        self.silence_reprompts = 0
        self.silent_pid: str | None = None
        self.silent_used = False
        self.delay_used = False
        self.barge_in_pid: str | None = None
        self.idle_probe_pid: str | None = None
        self.idle_probe_complete = False

    def socket_event(
        self,
        event: str,
        pid: str,
        socket_id: str,
        call_session_id: str | None = None,
        **fields: Any,
    ) -> None:
        record = {
            "event": event,
            "at_monotonic": time.monotonic(),
            "socket_id": socket_id,
            "investigation_id": self.inv["id"],
            "participant_id": pid,
            "call_session_id": call_session_id,
            **fields,
        }
        if self.socket_event_log is not None:
            self.socket_event_log.parent.mkdir(parents=True, exist_ok=True)
            with self.socket_event_log.open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, separators=(",", ":")) + "\n")

    async def state(self) -> dict[str, Any]:
        r = await self.core.get(f"/v1/investigations/{self.inv['id']}")
        r.raise_for_status()
        s = dict(r.json())
        self.most_at_once = max(self.most_at_once, len(waiting(s)))
        return s

    async def observe(self, pid: str, action: dict[str, Any]) -> str:
        tok = self.tokens[pid]
        h = {"Authorization": f"Bearer {tok['token']}"}
        sid = tok["scenario_id"]
        lock = self.observe_locks.setdefault(sid, asyncio.Lock())
        async with lock:
            location_id = str(action["location_id"])
            if action["requires_move"] or self.location_by_scenario.get(sid) != location_id:
                r = await self.sim.post(
                    f"/sim/v1/scenarios/{sid}/move",
                    json={"to": location_id},
                    headers=h,
                )
                r.raise_for_status()
                self.location_by_scenario[sid] = location_id
            r = await self.sim.post(
                f"/sim/v1/scenarios/{sid}/observe",
                json={"probe_id": action["probe_id"]},
                headers=h,
            )
            r.raise_for_status()
            return str(r.json()["value"])

    def _turn_task_done(self, task: asyncio.Task[None]) -> None:
        self.tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self.task_errors.append(error)

    async def _finish_turn_tasks(self) -> None:
        while self.tasks:
            await asyncio.gather(*tuple(self.tasks), return_exceptions=True)
        if self.task_errors:
            raise self.task_errors[0]

    async def bot(self, person: dict[str, Any]) -> None:
        """Answer every call to this person until the investigation no longer needs them."""
        pid = person["id"]
        lang = CLIP_LANG[person["languages"]["template_language"]]
        while True:
            s = await self.state()
            if s["status"] in DONE or (s["status"] == "acting"):
                if s["status"] in DONE and s["status"] != "decided":
                    return
                await asyncio.sleep(1)
                if s["status"] == "decided":
                    return
                continue
            if mine(s, pid) is None and not self.args.keep_calls_open:
                if (
                    not self.args.idle_probe
                    or self.idle_probe_complete
                    or self.idle_probe_pid not in (None, pid)
                    or pid == self.silent_pid
                ):
                    await asyncio.sleep(1)
                    continue
                self.idle_probe_pid = pid
            reason = await self.call(pid, lang)
            if reason == "silent":
                return

    async def call(self, pid: str, lang: str) -> str | None:
        url = (
            self.args.core.replace("http", "ws", 1)
            + f"/v1/investigations/{self.inv['id']}/participants/{pid}/call"
        )
        # No client pings: the core does not answer them while a call waits between questions
        # (browsers never send any); the call's own heartbeat frames keep the line alive.
        call_reason: str | None = None
        ws: Any = None
        call_open = False
        socket_id = uuid.uuid4().hex
        call_session_id: str | None = None
        call_end_received = False
        try:
            async with websockets.connect(url, max_size=2**23, ping_interval=None) as ws:
                self.call_metrics.opened(pid)
                call_open = True
                self.socket_event("open", pid, socket_id)
                await ws.send(
                    json.dumps(
                        {
                            "type": "start",
                            "token": self.tokens[pid]["token"],
                            "play": self.args.play,
                        }
                    )
                )
                async for raw in ws:
                    if isinstance(raw, bytes):
                        continue  # question audio: a real phone would play it
                    m = json.loads(raw)
                    kind = m["type"]
                    if kind == "ringing":
                        call_session_id = str(m.get("call_session_id", "")) or None
                        await ws.send(json.dumps({"type": "accept"}))
                    elif kind == "consent_request":
                        await ws.send(json.dumps({"type": "consent", "answer": "yes"}))
                    elif kind == "ready":
                        self.stt_streams_opened += 1
                        if pid == self.silent_pid and not self.silent_used:
                            self.silent_used = True
                            self.log.append(f"  {pid}: intentionally silent for the load check")
                            continue
                        if self.args.barge_in_first and self.barge_in_pid is None:
                            self.barge_in_pid = pid
                            await ws.send(b"\x00\x00" * 256)
                            self.log.append(f"  {pid}: sent an early synthetic speech frame")
                        # Read frames and timers while the bot prepares and speaks its answer.
                        task = asyncio.create_task(self.turn(ws, pid, lang, m))
                        self.tasks.add(task)
                        task.add_done_callback(self._turn_task_done)
                    elif kind == "tts_end":
                        if pid in self.t_answer:
                            self.next_ms.append((time.monotonic() - self.t_answer.pop(pid)) * 1000)
                        await ws.send(json.dumps({"type": "playback_done"}))
                    elif kind == "speech_start":
                        self.log.append(f"  {pid}: speech reached the core")
                    elif kind == "transcript":
                        if pid in self.t_eos:
                            self.stt_ms.append((time.monotonic() - self.t_eos[pid]) * 1000)
                        self.log.append(f"  {pid} said, emulated STT heard: {m['text']}")
                    elif kind == "question_withdrawn":
                        self.withdrawn += 1
                        self.log.append(f"  {pid}: question withdrawn, another answer settled it")
                    elif kind == "answer":
                        now = time.monotonic()
                        if pid in self.t_eos:
                            self.answer_ms.append((now - self.t_eos.pop(pid)) * 1000)
                        self.t_answer[pid] = now
                        self.voice_answers += 1
                        obs = m["result"]["observation"]
                        self.log.append(
                            f"  -> recorded {obs['probe_id']}={obs['outcome']} ({obs['modality']})"
                        )
                    elif kind == "empty_transcript":
                        self.log.append(f"  {pid}: nothing recognised, speaking again")
                        if pid in self.last_clip:
                            await self.speak(ws, pid, self.last_clip[pid])
                    elif kind == "reprompt":
                        self.silence_reprompts += 1
                    elif kind == "idle":
                        self.idle_heartbeats += 1
                        if pid == self.idle_probe_pid:
                            self.log.append(
                                f"  {pid}: idle heartbeat received; keeping the probe call open"
                            )
                            self.idle_probe_complete = True
                    elif kind == "stop_playback":
                        self.barge_ins += 1
                        self.log.append(f"  {pid}: prompt playback stopped for barge-in")
                    elif kind == "error" and m.get("fatal"):
                        self.log.append(f"  {pid}: error {m['code']}: {m['message']}")
                    elif kind == "call_end":
                        call_end_received = True
                        call_reason = str(m["reason"])
                        self.log.append(f"  call with {pid} ended: {call_reason}")
                        break
        except websockets.ConnectionClosed as exc:
            call_reason = "socket closed without call_end"
            self.log.append(f"  {pid}: call socket closed: {exc.code} {exc.reason}")
        finally:
            if ws is not None:
                if call_open:
                    self.call_metrics.closed(pid)
                self.call_closes.append(
                    {
                        "call_session_id": call_session_id,
                        "investigation_id": self.inv["id"],
                        "participant_id": pid,
                        "call_end_received": call_end_received,
                        "call_end_reason": call_reason,
                        "expected_close_code": (
                            4408 if self.args.silent_first and pid == self.silent_pid else 1000
                        ),
                        "code": ws.close_code,
                        "reason": ws.close_reason or "",
                    }
                )
                if call_open:
                    self.socket_event(
                        "close",
                        pid,
                        socket_id,
                        call_session_id,
                        code=ws.close_code,
                        reason=ws.close_reason or "",
                    )
        return call_reason

    async def turn(self, ws: Any, pid: str, lang: str, ready: dict[str, Any]) -> None:
        s = await self.state()
        q = next((w for w in waiting(s) if w["id"] == ready["question_id"]), None)
        if q is None:
            return
        value = await self.observe(pid, q["action"])
        if self.args.synthetic:
            clip = encode_synthetic_pcm(transcript_for_value(value))
        else:
            if self.clips is None:
                sys.exit("--clips is required unless --synthetic is set")
            clip_path = self.clips / f"{lang}__{value}.wav"
            if not clip_path.exists():
                sys.exit(f"missing clip {clip_path.name}")
            clip = pcm(clip_path)
        a = q["action"]
        self.log.append(
            f"Q{s['questions_asked']} to {pid} [{a['probe_id']}@{a['location_id']}]"
            f"{f' ({len(waiting(s))} in flight)' if len(waiting(s)) > 1 else ''}"
            f" {ready['text']!r}  (sim shows: {value})"
        )
        self.last_clip[pid] = clip
        barge_in = pid == self.barge_in_pid
        delay = 0.0 if barge_in else 0.3
        if self.args.delay_first_answer > 0 and not self.delay_used:
            delay += self.args.delay_first_answer
            self.delay_used = True
        await asyncio.sleep(delay)
        # The call can end while this bot is talking (e.g. its question was withdrawn).
        with contextlib.suppress(websockets.ConnectionClosed):
            await self.speak(ws, pid, clip, leading_silence=not barge_in)

    async def speak(self, ws: Any, pid: str, clip: bytes, *, leading_silence: bool = True) -> None:
        voice = (b"\x00\x00" * 4800 if leading_silence else b"") + clip
        audio = voice + b"\x00\x00" * 16000  # then a second of silence
        for i in range(0, len(audio), FRAME):
            await ws.send(audio[i : i + FRAME])
            if i < len(voice) <= i + FRAME:
                self.t_eos[pid] = time.monotonic() + 0.032  # this frame ends the voice
            await asyncio.sleep(0.032)  # real-time cadence
        await ws.send(json.dumps({"type": "commit"}))

    async def phase(self) -> None:
        """Bots play everyone except a human participant, who answers from their own phone."""
        bots = [p for p in PEOPLE if p["id"] != self.args.human]
        await asyncio.gather(*(self.bot(p) for p in bots), self.wait_for_human())
        await self._finish_turn_tasks()

    async def wait_for_human(self) -> None:
        """Return once nothing is pending for the human (the bots return on their own)."""
        if not self.args.human:
            return
        while True:
            s = await self.state()
            if s["status"] in DONE or (not waiting(s) and s["status"] != "acting"):
                return
            await asyncio.sleep(1)

    async def repair(self) -> None:
        inv = self.inv["id"]
        s = await self.state()
        self.log.append(
            f"DECISION {s['belief']['map_decision']} at P = "
            f"{s['belief']['map_decision_probability']:.3f} after {s['questions_asked']} questions"
        )
        r = await self.core.post(
            f"/v1/investigations/{inv}/approvals",
            json={"action": "reset_breaker", "target": "CB_C2_7", "participant_id": "p_imran"},
        )
        r.raise_for_status()
        aid = r.json()["approvals"][-1]["id"]
        r = await self.core.post(
            f"/v1/investigations/{inv}/approvals/{aid}/decision", json={"decision": "approve"}
        )
        r.raise_for_status()
        imran = {"Authorization": f"Bearer {self.tokens['p_imran']['token']}"}
        grant = await self.core.post(
            f"/v1/investigations/{inv}/approvals/{aid}/capability",
            params={"participant_id": "p_imran"},
            headers=imran,
        )
        grant.raise_for_status()
        g = grant.json()
        sid = self.tokens["p_imran"]["scenario_id"]
        move = await self.sim.post(
            f"/sim/v1/scenarios/{sid}/move", json={"to": g["location_id"]}, headers=imran
        )
        move.raise_for_status()
        self.location_by_scenario[sid] = str(g["location_id"])
        act = await self.sim.post(
            f"/sim/v1/scenarios/{sid}/act",
            json={"action": "reset_breaker", "target": "CB_C2_7", "capability": g["capability"]},
            headers=imran,
        )
        act.raise_for_status()
        r = await self.core.post(
            f"/v1/investigations/{inv}/interventions",
            json={"approval_id": aid, "participant_id": "p_imran"},
            headers=imran,
        )
        r.raise_for_status()
        self.log.append("REPAIR approved, capability collected, breaker reset, reported")

    async def main(self) -> int:
        before = (await self.core.get("/v1/voice/usage")).json().get("spent_today_inr", 0.0)
        if self.args.attach:  # continue an investigation already under way
            r = await self.core.get(f"/v1/investigations/{self.args.attach}")
        else:
            r = await self.core.post(
                "/v1/investigations",
                json={
                    "pack_id": "campus_block_c",
                    "participants": PEOPLE,
                    "report": {"text": "Floor 3 pe WiFi nahi chal raha", "reporter_id": "p_riya"},
                    "scenario": {
                        "seed": 19,
                        "fault": {"faults": [{"component_id": "CB_C2_7", "mode": "tripped"}]},
                    },
                    "max_parallel_calls": self.args.parallel,
                },
            )
        r.raise_for_status()
        self.inv = r.json()
        if self.args.silent_first:
            first = waiting(self.inv)
            self.silent_pid = first[0]["action"]["participant_id"] if first else None
        for p in PEOPLE:
            t = await self.core.post(
                f"/v1/investigations/{self.inv['id']}/participants/{p['id']}/token"
            )
            t.raise_for_status()
            self.tokens[p["id"]] = t.json()
        if self.args.human:
            tok = self.tokens[self.args.human]
            link = f"{self.args.public_url.rstrip('/')}/join/" + join_segment(
                {
                    "i": self.inv["id"],
                    "p": self.args.human,
                    "s": tok["scenario_id"],
                    "t": tok["token"],
                }
            )
            print(f"JOIN LINK for {self.args.human}: {link}", flush=True)
        await asyncio.wait_for(self.phase(), self.args.timeout)
        s = await self.state()
        if s["status"] == "decided" and s["belief"]["map_decision"] == "DISPATCH_ELECTRICIAN_DB_C2":
            await self.repair()
            await asyncio.wait_for(self.phase(), self.args.timeout)
        s = await self.state()
        reveal = (await self.core.post(f"/v1/investigations/{self.inv['id']}/reveal")).json()
        replay = (await self.core.get(f"/v1/investigations/{self.inv['id']}/replay")).json()
        after = (await self.core.get("/v1/voice/usage")).json().get("spent_today_inr", 0.0)
        print("\n".join(self.log))
        gt = reveal.get("ground_truth") or {}
        sealed = (gt.get("reveal") or {}).get("commitment_verified", gt.get("commitment_verified"))
        replay_identical = bool(
            replay.get("identical")
            and replay.get("replayed_sha256") == replay.get("recorded_sha256")
        )

        def med(xs: list[float]) -> str:
            return f"{statistics.median(xs):.0f} ms (n={len(xs)})" if xs else "-"

        label = (
            "EMULATED LATENCY (local test provider)"
            if self.args.synthetic
            else "LATENCY (private, Gnani EULA: do not publish)"
        )
        print(
            f"\n{label}\n"
            f"  end of speech -> transcript:            {med(self.stt_ms)}\n"
            f"  end of speech -> answer recorded:       {med(self.answer_ms)}\n"
            f"  answer recorded -> next question audio: {med(self.next_ms)}"
        )
        print(
            f"\nFINAL status before reveal: {s['status']} | questions: {s['questions_asked']} | "
            f"voice answers: {self.voice_answers} | most questions in flight at once: "
            f"{self.most_at_once} | withdrawn: {self.withdrawn}\n"
            f"reveal: decision correct = {gt.get('correct')}, commitment verified = "
            f"{sealed}\n"
            f"replay byte-identical: {replay_identical}\n"
            f"voice spend for this run: Rs {after - before:.2f}"
        )
        result = {
            "investigation_id": self.inv["id"],
            "status": s["status"],
            "decision": s["belief"]["map_decision"],
            "questions_asked": s["questions_asked"],
            "voice_answers": self.voice_answers,
            "stt_streams_opened": self.stt_streams_opened,
            "revealed_correct": gt.get("correct"),
            "commitment_verified": sealed,
            "replay_identical": replay_identical,
            "replay_replayed_sha256": replay.get("replayed_sha256"),
            "replay_recorded_sha256": replay.get("recorded_sha256"),
            "withdrawn_questions": self.withdrawn,
            "idle_heartbeats": self.idle_heartbeats,
            "barge_ins": self.barge_ins,
            "silence_reprompts": self.silence_reprompts,
            "silent_participant_released": any(
                close["code"] == 4408 and close["participant_id"] == self.silent_pid
                for close in self.call_closes
            ),
            "call_socket_closes": self.call_closes,
            "call_socket_metrics": self.call_metrics.snapshot(),
            "max_questions_in_flight": self.most_at_once,
        }
        if self.args.synthetic:
            result["emulated_eos_to_transcript_ms"] = self.stt_ms
            result["emulated_eos_to_answer_ms"] = self.answer_ms
        if self.args.synthetic or self.socket_event_log is not None:
            print("LOAD_RESULT_JSON=" + json.dumps(result, separators=(",", ":")), flush=True)
        return (
            0
            if s["status"] == "verified"
            and gt.get("correct") is True
            and sealed is True
            and replay_identical
            else 1
        )


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", default="http://127.0.0.1:8000")
    ap.add_argument("--sim", default="http://127.0.0.1:8100")
    ap.add_argument("--clips")
    ap.add_argument(
        "--socket-events", help="append call-socket lifecycle events to this JSONL file"
    )
    ap.add_argument(
        "--synthetic", action="store_true", help="encode deterministic local test audio"
    )
    ap.add_argument(
        "--keep-calls-open", action="store_true", help="connect all bots before they are asked"
    )
    ap.add_argument(
        "--idle-probe",
        action="store_true",
        help="open one otherwise-idle call until it receives a heartbeat",
    )
    ap.add_argument(
        "--silent-first", action="store_true", help="leave the first assigned call silent"
    )
    ap.add_argument("--delay-first-answer", type=float, default=0.0)
    ap.add_argument(
        "--barge-in-first",
        action="store_true",
        help="keep question playback active until the first answer begins",
    )
    ap.add_argument("--play", action="store_true", help="have Timbre speak each question")
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--human", help="participant id answered by a person on their phone")
    ap.add_argument("--attach", help="continue this investigation instead of creating one")
    ap.add_argument("--public-url", default="http://localhost:3002", help="web app address")
    ap.add_argument(
        "--parallel", type=int, default=1, choices=[1, 2, 3], help="people asked at once"
    )
    args = ap.parse_args()
    if not args.synthetic and not args.clips:
        ap.error("--clips is required unless --synthetic is set")
    sys.exit(asyncio.run(Run(args).main()))


if __name__ == "__main__":
    main()
