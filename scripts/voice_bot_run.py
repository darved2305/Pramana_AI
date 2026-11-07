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
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import random
import statistics
import sys
import time
import wave
from pathlib import Path
from typing import Any

import httpx
import websockets
from core_auth import automation_headers
from demo_rehearse import scenario_request
from gnani_live_check import to_16k_mono_pcm

from pramana_core.language.speakable import speakable

PEOPLE = [
    {
        "id": "p_riya",
        "display_name": "Riya",
        "roles": ["student"],
        "skill": "lay",
        "location_id": "F3_R304",
        "languages": {
            "stt_candidates": ["hi-IN", "en-IN"],
            "template_language": "hi-en",
            "codemix": True,
        },
    },
    {
        "id": "p_mahesh",
        "display_name": "Mahesh",
        "roles": ["guard"],
        "skill": "access",
        "location_id": "GUARD_DESK",
        "languages": {"stt_candidates": ["mr-IN", "hi-IN"], "template_language": "mr"},
    },
    {
        "id": "p_imran",
        "display_name": "Imran",
        "roles": ["electrician"],
        "skill": "technician",
        "location_id": "MAINT_ROOM",
        "languages": {"stt_candidates": ["hi-IN"], "template_language": "hi"},
    },
]
CLIP_LANG = {"hi-en": "hi", "hi": "hi", "mr": "mr", "en": "hi"}
DONE = {"decided", "abstained", "verified", "not_verified", "closed"}
FRAME = 1024  # bytes: 32 ms of 16 kHz PCM16
Audio = Path | bytes


def clip_name(clip: Audio) -> str:
    return clip.stem if isinstance(clip, Path) else "synthesized answer"


def rehearsal_passed(
    scenario: str,
    variant: str,
    state: dict[str, Any],
    *,
    correct: bool | None,
    sealed: bool,
    identical: bool,
    call_errors: list[str],
) -> bool:
    if not sealed or not identical or call_errors:
        return False
    if scenario == "S1":
        return state["status"] == "verified" and correct is True
    if scenario == "S2":
        return state["status"] == "decided" and correct is True and bool(state.get("disagreements"))
    expected = "failed" if variant == "adversary" else "passed"
    return any(c["status"] == expected for c in state.get("presence_checks", [])) and (
        state["status"] == "abstained" or (state["status"] == "decided" and correct is True)
    )


def join_segment(payload: dict[str, str]) -> str:
    """The participant page's link segment (apps/web/src/lib/join.ts ``encodeJoin``)."""
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def pcm(path: Path) -> bytes:
    with wave.open(str(path)) as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
            sys.exit(f"{path.name}: clips must be 16 kHz mono PCM16")
        return w.readframes(w.getnframes())


def waiting(s: dict[str, Any]) -> list[dict[str, Any]]:
    """Every question in flight (one unless the investigation asks in parallel)."""
    qs = s.get("pending_questions")
    if qs:
        return list(qs)
    return [s["pending_question"]] if s.get("pending_question") else []


def mine(s: dict[str, Any], pid: str) -> dict[str, Any] | None:
    return next((q for q in waiting(s) if q["action"]["participant_id"] == pid), None)


class Run:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.core = httpx.AsyncClient(base_url=args.core, headers=automation_headers(), timeout=60)
        self.sim = httpx.AsyncClient(base_url=args.sim, timeout=30)
        self.variants = Path(args.variants) if getattr(args, "variants", None) else None
        self.rng = random.Random(getattr(args, "seed", 0))
        self.think = tuple(
            float(x) for x in (getattr(args, "think_s", None) or "0.3,0.3").split(",")
        )
        junk = getattr(args, "junk", None)
        self.junk = sorted(Path(junk).glob("*.wav")) if junk else []
        self.junk_p = float(getattr(args, "junk_p", 0.0) or 0.0)
        self.silent_p = float(getattr(args, "silent_p", 0.0) or 0.0)
        self.said: dict[str, tuple[str, str, str]] = {}
        """Per participant, the last thing spoken: (kind, clip name, true value)."""
        self.truth_clip: dict[str, Audio] = {}
        self.silent_turns: set[str] = set()
        self.outcomes: list[dict[str, str]] = []
        """Every recorded answer: what was said (junk or truth) and what the core recorded."""
        self.reprompts = 0
        self.walked_back = 0
        self.clips = Path(args.clips)
        self.tokens: dict[str, dict[str, str]] = {}
        self.inv: dict[str, Any] = {}
        self.log: list[str] = []
        self.voice_answers = 0
        # Latency as the caller experiences it (private: printed, never committed).
        self.t_eos: dict[str, float] = {}
        """Per call: when the answer's voice ended (end of the clip, before the silence)."""
        self.t_answer: dict[str, float] = {}
        self.stt_ms: list[float] = []
        self.answer_ms: list[float] = []
        self.next_ms: list[float] = []
        self.tasks: set[asyncio.Task[None]] = set()
        self.lock = asyncio.Lock()
        self.last_clip: dict[str, Audio] = {}
        self.speakers: dict[str, asyncio.Task[None]] = {}
        self.call_errors: list[str] = []
        self.people = PEOPLE
        self.question_kind: dict[str, str] = {}
        self.withdrawn = 0
        self.most_at_once = 0

    async def state(self) -> dict[str, Any]:
        r = await self.core.get(f"/v1/investigations/{self.inv['id']}")
        r.raise_for_status()
        s = dict(r.json())
        self.most_at_once = max(self.most_at_once, len(waiting(s)))
        return s

    async def observe(self, pid: str, action: dict[str, Any]) -> str:
        if (
            getattr(self.args, "scenario", "S1") == "S7"
            and getattr(self.args, "variant", "honest") == "adversary"
            and pid == "p_mahesh"
            and action["location_id"] == "IDF2"
        ):
            # Scripted false claims from the guard desk; never peek at the remote card.
            return {
                "switch_leds": "green",
                "nvr_screen": "off",
                "closet_light": "off",
                "room_socket": "off",
            }[action["probe_id"]]
        tok = self.tokens[pid]
        h = {"Authorization": f"Bearer {tok['token']}"}
        sid = tok["scenario_id"]
        if action["requires_move"]:
            r = await self.sim.post(
                f"/sim/v1/scenarios/{sid}/move", json={"to": action["location_id"]}, headers=h
            )
            r.raise_for_status()
        r = await self.sim.post(
            f"/sim/v1/scenarios/{sid}/observe", json={"probe_id": action["probe_id"]}, headers=h
        )
        if r.status_code == 409 and r.json().get("error", {}).get("code") == "NOT_OBSERVABLE_HERE":
            # Walked off for a question that was then withdrawn: a person walks back first.
            await self.sim.post(
                f"/sim/v1/scenarios/{sid}/move", json={"to": action["location_id"]}, headers=h
            )
            self.walked_back += 1
            r = await self.sim.post(
                f"/sim/v1/scenarios/{sid}/observe", json={"probe_id": action["probe_id"]}, headers=h
            )
        r.raise_for_status()
        return str(r.json()["value"])

    def start_speaker(self, pid: str, coroutine: Any) -> None:
        previous = self.speakers.get(pid)
        if previous is not None:
            previous.cancel()
        task = asyncio.create_task(coroutine)
        self.speakers[pid] = task
        self.tasks.add(task)

        def completed(task: asyncio.Task[None]) -> None:
            self.tasks.discard(task)
            if not task.cancelled() and (error := task.exception()) is not None:
                self.call_errors.append(f"{pid}: {type(error).__name__}: {error}")

        task.add_done_callback(completed)

    async def synthesize_answer(self, phrase: str, language: str) -> bytes:
        response = await self.core.post(
            "/v1/voice/tts",
            json={
                "text": phrase,
                "language": {"mr": "mr-IN", "hi": "hi-IN", "en": "en-IN", "hi-en": "hi-en"}[
                    language
                ],
            },
        )
        response.raise_for_status()
        return to_16k_mono_pcm(response.content)

    async def presence_audio(self, pid: str, q: dict[str, Any]) -> bytes:
        tok = self.tokens[pid]
        response = await self.sim.get(
            f"/sim/v1/scenarios/{tok['scenario_id']}/view",
            headers={"Authorization": f"Bearer {tok['token']}"},
        )
        response.raise_for_status()
        view = response.json()
        labels = view.get("labels", []) if view["location_id"] == q["action"]["location_id"] else []
        # The challenge never moves a person. Someone still at the desk cannot read the label.
        phrase = (
            speakable(" ".join(labels[0]["value"]), q["language"])
            if labels
            else {
                "mr": "मला इथून लेबल दिसत नाही",
                "hi": "मुझे यहाँ से लेबल नहीं दिखता",
                "hi-en": "Mujhe yahan se label nahi dikhta",
                "en": "I cannot see the label from here",
            }[q["language"]]
        )
        return await self.synthesize_answer(phrase, q["language"])

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
            if mine(s, pid) is None:
                await asyncio.sleep(1)
                continue
            await self.call(pid, lang)

    async def call(self, pid: str, lang: str) -> None:
        url = (
            self.args.core.replace("http", "ws", 1)
            + f"/v1/investigations/{self.inv['id']}/participants/{pid}/call"
        )
        # No client pings: the core does not answer them while a call waits between questions
        # (browsers never send any); the call's own heartbeat frames keep the line alive.
        async with websockets.connect(url, max_size=2**23, ping_interval=None) as ws:
            await ws.send(
                json.dumps(
                    {"type": "start", "token": self.tokens[pid]["token"], "play": self.args.play}
                )
            )
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue  # question audio: a real phone would play it
                m = json.loads(raw)
                kind = m["type"]
                if kind == "ringing":
                    await ws.send(json.dumps({"type": "accept"}))
                elif kind == "consent_request":
                    await ws.send(json.dumps({"type": "consent", "answer": "yes"}))
                elif kind == "ready":
                    # Speak in a task, so frames are read (and timed) while the bot talks.
                    self.question_kind[pid] = m.get("kind", "probe")
                    self.start_speaker(pid, self.turn(ws, pid, lang, m))
                elif kind == "tts_end":
                    if pid in self.t_answer:
                        self.next_ms.append((time.monotonic() - self.t_answer.pop(pid)) * 1000)
                    await ws.send(json.dumps({"type": "playback_done"}))
                elif kind == "transcript":
                    if pid in self.t_eos:
                        self.stt_ms.append((time.monotonic() - self.t_eos[pid]) * 1000)
                    self.log.append(f"  {pid} said, Prisma heard: {m['text']}")
                elif kind == "question_withdrawn":
                    if task := self.speakers.get(pid):
                        task.cancel()
                    self.withdrawn += 1
                    self.log.append(f"  {pid}: question withdrawn, another answer settled it")
                elif kind == "answer":
                    now = time.monotonic()
                    if pid in self.t_eos:
                        self.answer_ms.append((now - self.t_eos.pop(pid)) * 1000)
                    self.t_answer[pid] = now
                    self.voice_answers += 1
                    if self.question_kind.get(pid) == "challenge":
                        self.log.append(f"  {pid}: presence reading submitted by voice")
                        continue  # result.observation refers to the earlier claim, not this reading
                    obs = m["result"]["observation"]
                    self.log.append(
                        f"  -> recorded {obs['probe_id']}={obs['outcome']} ({obs['modality']})"
                    )
                    kind_said, clip_said, truth = self.said.get(pid, ("truth", "?", "?"))
                    self.outcomes.append(
                        {
                            "said": kind_said,
                            "clip": clip_said,
                            "truth": truth,
                            "recorded": obs["outcome"],
                            "probe": obs["probe_id"],
                            "state": obs.get("state", ""),
                        }
                    )
                elif kind == "empty_transcript":
                    self.log.append(f"  {pid}: nothing recognised, speaking again")
                    clip = self.truth_clip.get(pid) or self.last_clip.get(pid)
                    if clip is not None:
                        self.said[pid] = (
                            "truth",
                            clip_name(clip),
                            self.said.get(pid, ("", "", "?"))[2],
                        )
                        await self.speak(ws, pid, clip)
                elif kind == "reprompt":
                    self.reprompts += 1
                    self.log.append(f"  {pid}: silence, Pramana asked again")
                    if pid in self.silent_turns and pid in self.truth_clip:
                        self.silent_turns.discard(pid)
                        clip = self.truth_clip[pid]
                        self.said[pid] = (
                            "truth",
                            clip_name(clip),
                            self.said.get(pid, ("", "", "?"))[2],
                        )
                        self.start_speaker(pid, self.speak_after(ws, pid, clip, 1.0))
                elif kind == "error" and m.get("fatal"):
                    self.call_errors.append(f"{pid}: {m['code']}: {m['message']}")
                    self.log.append(f"  {pid}: error {m['code']}: {m['message']}")
                elif kind == "call_end":
                    if task := self.speakers.get(pid):
                        task.cancel()
                    self.log.append(f"  call with {pid} ended: {m['reason']}")
                    return

    async def turn(self, ws: Any, pid: str, lang: str, ready: dict[str, Any]) -> None:
        s = await self.state()
        q = next((w for w in waiting(s) if w["id"] == ready["question_id"]), None)
        if q is None:
            return
        if q.get("kind") == "challenge":
            clip = await self.presence_audio(pid, q)
            self.last_clip[pid] = self.truth_clip[pid] = clip
            self.log.append(f"  {pid}: answering presence check from own simulator card")
            await self.speak(ws, pid, clip)
            return
        value = await self.observe(pid, q["action"])
        if q["language"] == "en":
            from text_investigation import PHRASES

            clip = await self.synthesize_answer(PHRASES[value], "en")
        else:
            clip = self.pick_clip(lang, q["action"]["probe_id"], value)
        a = q["action"]
        self.log.append(
            f"Q{s['questions_asked']} to {pid} [{a['probe_id']}@{a['location_id']}]"
            f"{f' ({len(waiting(s))} in flight)' if len(waiting(s)) > 1 else ''}"
            f" {ready['text']!r}  (answer: {value}; says take {clip_name(clip)})"
        )
        self.last_clip[pid] = clip
        self.truth_clip[pid] = clip
        roll = self.rng.random()
        if self.silent_p and roll < self.silent_p:
            # Say nothing this time: the call should ask again after its silence timer.
            self.silent_turns.add(pid)
            self.said[pid] = ("silent", "-", value)
            self.log.append(f"  {pid} stays silent")
            return
        if self.junk and roll < self.silent_p + self.junk_p:
            junk = self.rng.choice(self.junk)
            self.said[pid] = ("junk", junk.stem, value)
            self.log.append(f"  {pid} says something irrelevant: {junk.stem}")
            clip = junk
        else:
            self.said[pid] = ("truth", clip_name(clip), value)
        await asyncio.sleep(self.rng.uniform(*self.think))  # a person takes a moment
        # The call can end while this bot is talking (e.g. its question was withdrawn).
        with contextlib.suppress(websockets.ConnectionClosed):
            await self.speak(ws, pid, clip)

    async def speak_after(self, ws: Any, pid: str, clip: Audio, delay: float) -> None:
        await asyncio.sleep(delay)
        with contextlib.suppress(websockets.ConnectionClosed):
            await self.speak(ws, pid, clip)

    def pick_clip(self, lang: str, probe_id: str, value: str) -> Path:
        """The answer clip. With ``--variants``, a random take of this answer to this question
        (other voices, phrasings, phone-band or noisy audio, named
        ``<lang>__<probe>__<value>__<tag>.wav``), else the one plain clip."""
        base = self.clips / f"{lang}__{value}.wav"
        takes = (
            sorted(self.variants.glob(f"{lang}__{probe_id}__{value}__*.wav"))
            if self.variants
            else []
        )
        if takes:
            return self.rng.choice([*takes, base] if base.exists() else takes)
        if not base.exists():
            sys.exit(f"missing clip {base.name}")
        return base

    async def speak(self, ws: Any, pid: str, clip: Audio) -> None:
        voice = b"\x00\x00" * 4800 + (pcm(clip) if isinstance(clip, Path) else clip)
        audio = voice + b"\x00\x00" * 16000  # then a second of silence
        for i in range(0, len(audio), FRAME):
            await ws.send(audio[i : i + FRAME])
            if i < len(voice) <= i + FRAME:
                self.t_eos[pid] = time.monotonic() + 0.032  # this frame ends the voice
            await asyncio.sleep(0.032)  # real-time cadence
        await ws.send(json.dumps({"type": "commit"}))

    async def phase(self) -> None:
        """Bots play everyone except a human participant, who answers from their own phone."""
        bots = [p for p in self.people if p["id"] != self.args.human]
        tasks = [asyncio.create_task(self.bot(p)) for p in bots]
        tasks.append(asyncio.create_task(self.wait_for_human()))
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

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
        await self.sim.post(
            f"/sim/v1/scenarios/{sid}/move", json={"to": g["location_id"]}, headers=imran
        )
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
        try:
            return await self._main()
        finally:
            for task in self.tasks:
                task.cancel()
            await asyncio.gather(*self.tasks, return_exceptions=True)
            await self.core.aclose()
            await self.sim.aclose()

    async def _main(self) -> int:
        before = (await self.core.get("/v1/voice/usage")).json().get("spent_today_inr", 0.0)
        if self.args.attach:  # continue an investigation already under way
            r = await self.core.get(f"/v1/investigations/{self.args.attach}")
        else:
            r = await self.core.post(
                "/v1/investigations",
                json={
                    **scenario_request(getattr(self.args, "scenario", "S1"), seed=19),
                    "max_parallel_calls": self.args.parallel,
                },
            )
        r.raise_for_status()
        self.inv = r.json()
        self.people = self.inv["participants"]
        for p in self.people:
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
        response = await self.core.post(f"/v1/investigations/{self.inv['id']}/reveal")
        response.raise_for_status()
        reveal = response.json()
        response = await self.core.get(f"/v1/investigations/{self.inv['id']}/replay")
        response.raise_for_status()
        replay = response.json()
        after = (await self.core.get("/v1/voice/usage")).json().get("spent_today_inr", 0.0)
        print("\n".join(self.log))
        gt = reveal.get("ground_truth") or {}
        sealed = (gt.get("reveal") or {}).get("commitment_verified", gt.get("commitment_verified"))
        sealed = (
            sealed is True
            and (gt.get("reveal") or {}).get("commitment") == self.inv["sealed_commitment"]
        )

        def med(xs: list[float]) -> str:
            return f"{statistics.median(xs):.0f} ms (n={len(xs)})" if xs else "-"

        print(
            "\nLATENCY (private, Gnani EULA: do not publish)\n"
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
            f"replay identical: {replay.get('identical')}\n"
            f"voice spend for this run: Rs {after - before:.2f}"
        )
        junk = [o for o in self.outcomes if o["said"] == "junk"]
        truth = [o for o in self.outcomes if o["said"] == "truth"]
        invented = [o for o in junk if o["recorded"] != "unknown"]
        misheard = [o for o in truth if o["recorded"] not in ("unknown", o["truth"])]
        print(
            f"edge: {len(junk)} irrelevant utterances, {len(invented)} became evidence | "
            f"{len(truth)} true answers, {len(misheard)} recorded wrong | "
            f"re-prompts after silence: {self.reprompts} | walked back: {self.walked_back}"
        )
        scenario = getattr(self.args, "scenario", "S1")
        variant = getattr(self.args, "variant", "honest")
        passed = rehearsal_passed(
            scenario,
            variant,
            s,
            correct=gt.get("correct"),
            sealed=sealed is True,
            identical=replay.get("identical") is True,
            call_errors=self.call_errors,
        )
        if getattr(self.args, "summary", None):
            # Public integration facts only. No transcripts, label readings, or Gnani measurements.
            summary = {
                "scenario": scenario,
                "variant": variant,
                "participants": "synthetic voice bots",
                "investigation_id": self.inv["id"],
                "status": s["status"],
                "voice_answers": self.voice_answers,
                "most_in_flight": self.most_at_once,
                "correct": gt.get("correct"),
                "commitment_verified": sealed,
                "replay_identical": replay.get("identical"),
                "passed": passed,
                "presence_checks": s.get("presence_checks", []),
                "disagreement_count": len(s.get("disagreements", [])),
                "call_errors": self.call_errors,
            }
            path = Path(self.args.summary)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        if getattr(self.args, "report", None):
            Path(self.args.report).write_text(
                json.dumps(
                    {
                        "status": s["status"],
                        "correct": gt.get("correct"),
                        "replay_identical": replay.get("identical"),
                        "reprompts": self.reprompts,
                        "walked_back": self.walked_back,
                        "answers": self.outcomes,
                    },
                    ensure_ascii=False,
                    indent=1,
                ),
                encoding="utf-8",
            )
        return 0 if passed else 1


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", default="http://127.0.0.1:8000")
    ap.add_argument("--sim", default="http://127.0.0.1:8100")
    ap.add_argument("--clips", required=True)
    ap.add_argument("--play", action="store_true", help="have Timbre speak each question")
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--human", help="participant id answered by a person on their phone")
    ap.add_argument("--attach", help="continue this investigation instead of creating one")
    ap.add_argument("--scenario", choices=["S1", "S2", "S7"], default="S1")
    ap.add_argument("--variant", choices=["honest", "adversary"], default="honest")
    ap.add_argument("--summary", help="public integration summary, without speech measurements")
    ap.add_argument(
        "--variants",
        help="folder of other takes, <lang>__<probe>__<value>__<tag>.wav (e.g. MMS voices, "
        "phone-band and noisy versions): each answer uses a random one",
    )
    ap.add_argument("--think-s", default="0.3,0.3", help="pause before answering: min,max seconds")
    ap.add_argument("--seed", type=int, default=0, help="seed for the takes and pauses")
    ap.add_argument("--junk", help="folder of irrelevant or vague speech, noise (any .wav)")
    ap.add_argument("--junk-p", type=float, default=0.0, help="chance of saying junk first")
    ap.add_argument("--silent-p", type=float, default=0.0, help="chance of staying silent once")
    ap.add_argument("--report", help="write every recorded answer, with what was said, as JSON")
    ap.add_argument("--public-url", default="http://localhost:3002", help="web app address")
    ap.add_argument(
        "--parallel", type=int, default=1, choices=[1, 2, 3], help="people asked at once"
    )
    sys.exit(asyncio.run(Run(ap.parse_args()).main()))


if __name__ == "__main__":
    main()
