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

Usage: python scripts/voice_bot_run.py --clips <dir> [--core URL] [--sim URL] [--play]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import wave
from pathlib import Path
from typing import Any

import httpx
import websockets
from core_auth import automation_headers

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


def pcm(path: Path) -> bytes:
    with wave.open(str(path)) as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
            sys.exit(f"{path.name}: clips must be 16 kHz mono PCM16")
        return w.readframes(w.getnframes())


class Run:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.core = httpx.AsyncClient(base_url=args.core, headers=automation_headers(), timeout=60)
        self.sim = httpx.AsyncClient(base_url=args.sim, timeout=30)
        self.clips = Path(args.clips)
        self.tokens: dict[str, dict[str, str]] = {}
        self.inv: dict[str, Any] = {}
        self.log: list[str] = []
        self.voice_answers = 0
        self.lock = asyncio.Lock()
        self.last_clip: Path | None = None

    async def state(self) -> dict[str, Any]:
        r = await self.core.get(f"/v1/investigations/{self.inv['id']}")
        r.raise_for_status()
        return dict(r.json())

    async def observe(self, pid: str, action: dict[str, Any]) -> str:
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
        r.raise_for_status()
        return str(r.json()["value"])

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
            q = s["pending_question"]
            if q is None or q["action"]["participant_id"] != pid:
                await asyncio.sleep(1)
                continue
            await self.call(pid, lang)

    async def call(self, pid: str, lang: str) -> None:
        url = (
            self.args.core.replace("http", "ws", 1)
            + f"/v1/investigations/{self.inv['id']}/participants/{pid}/call"
        )
        async with websockets.connect(url, max_size=2**23) as ws:
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
                    await self.turn(ws, pid, lang, m)
                elif kind == "tts_end":
                    await ws.send(json.dumps({"type": "playback_done"}))
                elif kind == "transcript":
                    self.log.append(f"  {pid} said, Prisma heard: {m['text']}")
                elif kind == "answer":
                    self.voice_answers += 1
                    obs = m["result"]["observation"]
                    self.log.append(
                        f"  -> recorded {obs['probe_id']}={obs['outcome']} ({obs['modality']})"
                    )
                elif kind == "empty_transcript":
                    self.log.append(f"  {pid}: nothing recognised, speaking again")
                    if self.last_clip is not None:
                        await self.speak(ws, self.last_clip)
                elif kind == "error" and m.get("fatal"):
                    self.log.append(f"  {pid}: error {m['code']}: {m['message']}")
                elif kind == "call_end":
                    self.log.append(f"  call with {pid} ended: {m['reason']}")
                    return

    async def turn(self, ws: Any, pid: str, lang: str, ready: dict[str, Any]) -> None:
        s = await self.state()
        q = s["pending_question"]
        if q is None or q["id"] != ready["question_id"]:
            return
        value = await self.observe(pid, q["action"])
        clip = self.clips / f"{lang}__{value}.wav"
        if not clip.exists():
            sys.exit(f"missing clip {clip.name}")
        a = q["action"]
        self.log.append(
            f"Q{s['questions_asked']} to {pid} [{a['probe_id']}@{a['location_id']}]"
            f" {ready['text']!r}  (sim shows: {value})"
        )
        self.last_clip = clip
        await asyncio.sleep(0.3)
        await self.speak(ws, clip)

    async def speak(self, ws: Any, clip: Path) -> None:
        audio = b"\x00\x00" * 4800 + pcm(clip) + b"\x00\x00" * 16000  # lead-in, then silence
        for i in range(0, len(audio), FRAME):
            await ws.send(audio[i : i + FRAME])
            await asyncio.sleep(0.032)  # real-time cadence
        await ws.send(json.dumps({"type": "commit"}))

    async def phase(self) -> None:
        await asyncio.gather(*(self.bot(p) for p in PEOPLE))

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
        before = (await self.core.get("/v1/voice/usage")).json().get("spent_today_inr", 0.0)
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
            },
        )
        r.raise_for_status()
        self.inv = r.json()
        for p in PEOPLE:
            t = await self.core.post(
                f"/v1/investigations/{self.inv['id']}/participants/{p['id']}/token"
            )
            t.raise_for_status()
            self.tokens[p["id"]] = t.json()
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
        print(
            f"\nFINAL status before reveal: {s['status']} | questions: {s['questions_asked']} | "
            f"voice answers: {self.voice_answers}\n"
            f"reveal: decision correct = {gt.get('correct')}, commitment verified = "
            f"{sealed}\n"
            f"replay identical: {replay.get('identical')}\n"
            f"voice spend for this run: Rs {after - before:.2f}"
        )
        return 0 if s["status"] == "verified" and replay.get("identical") else 1


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", default="http://127.0.0.1:8000")
    ap.add_argument("--sim", default="http://127.0.0.1:8100")
    ap.add_argument("--clips", required=True)
    ap.add_argument("--play", action="store_true", help="have Timbre speak each question")
    ap.add_argument("--timeout", type=float, default=900.0)
    sys.exit(asyncio.run(Run(ap.parse_args()).main()))


if __name__ == "__main__":
    main()
