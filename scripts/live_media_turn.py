"""One live spoken turn through the per-question media socket (spends a few paise of credits).

Creates scenario S1 on a running core, synthesises the addressee's truthful answer with Timbre
(from what the simulator shows them), streams it as 16 kHz PCM through
``WS /v1/investigations/{id}/questions/{qid}/media`` with their join token, and checks that the
answer was recorded. It prints integration facts only (frame sequence, recorded outcome); under
the Gnani EULA measured accuracy and latency stay out of the repository.

Usage: python scripts/live_media_turn.py [--core http://127.0.0.1:8000] [--sim http://127.0.0.1:8100]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx
import websockets
from core_auth import automation_headers
from gnani_live_check import to_16k_mono_pcm

ANSWERS = {  # truthful answer per observed value, in the participant's template language
    "hi-en": {
        "yes": "haan chal raha hai",
        "no": "nahi, kuch nahi chal raha",
        "on": "haan, chalu hai",
        "off": "nahi, band hai",
    },
    "hi": {"yes": "हाँ, चल रहा है", "no": "नहीं, नहीं चल रहा", "on": "हाँ, चालू है", "off": "नहीं, बंद है"},
    "mr": {"yes": "हो, चालू आहे", "no": "नाही, चालत नाही", "on": "हो, चालू आहे", "off": "नाही, बंद आहे"},
    "en": {
        "yes": "yes it works",
        "no": "no, nothing works",
        "on": "yes it is on",
        "off": "no, it is off",
    },
}
HINGLISH = {  # the test bot's phrases (services/core/tests/participant_bot.py), for any other value
    "green": "lights green hain",
    "amber": "orange dikh rahi hain",
    "red": "laal hai",
    "up": "breaker upar hai",
    "tripped": "breaker neeche hai, trip hai",
    "no_network": "NAVA-WiFi dikh hi nahi raha",
    "stuck_connecting": "connecting pe atka hai",
    "connected": "connected hai",
}
TTS_LANG = {"hi-en": "hi-en", "hi": "hi-IN", "mr": "mr-IN", "en": "en-IN"}

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


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", default="http://127.0.0.1:8000")
    ap.add_argument("--sim", default="http://127.0.0.1:8100")
    args = ap.parse_args()
    async with (
        httpx.AsyncClient(base_url=args.core, timeout=60, headers=automation_headers()) as core,
        httpx.AsyncClient(base_url=args.sim, timeout=30) as sim,
    ):
        inv = (
            await core.post(
                "/v1/investigations",
                json={
                    "pack_id": "campus_block_c",
                    "participants": PEOPLE,
                    "report": {"text": "Floor 3 pe WiFi nahi chal raha", "reporter_id": "p_riya"},
                    "scenario": {"seed": 19, "fault": "random"},
                },
            )
        ).json()
        q = inv["pending_question"]
        a = q["action"]
        person = next(p for p in PEOPLE if p["id"] == a["participant_id"])
        lang = person["languages"]["template_language"]  # type: ignore[index]
        tok = (
            await core.post(
                f"/v1/investigations/{inv['id']}/participants/{a['participant_id']}/token"
            )
        ).json()
        bearer = {"Authorization": f"Bearer {tok['token']}"}
        if a["requires_move"]:
            await sim.post(
                f"/sim/v1/scenarios/{tok['scenario_id']}/move",
                json={"to": a["location_id"]},
                headers=bearer,
            )
        seen = (
            await sim.post(
                f"/sim/v1/scenarios/{tok['scenario_id']}/observe",
                json={"probe_id": a["probe_id"]},
                headers=bearer,
            )
        ).json()["value"]
        phrase, tts_lang = ANSWERS[lang].get(seen), TTS_LANG[lang]
        if phrase is None:
            phrase, tts_lang = HINGLISH.get(seen), "hi-en"
        if phrase is None:
            print(f"no phrase for observed value {seen!r}; outcomes {q['outcomes']}")
            return 2
        wav = await core.post("/v1/voice/tts", json={"text": phrase, "language": tts_lang})
        wav.raise_for_status()
        pcm = to_16k_mono_pcm(wav.content)
        url = (
            args.core.replace("http", "ws", 1)
            + f"/v1/investigations/{inv['id']}/questions/{q['id']}/media"
        )
        frames: list[str] = []
        result: dict[str, object] = {}
        async with websockets.connect(url, max_size=2**22) as ws:
            await ws.send(
                json.dumps({"type": "start", "token": tok["token"], "play_question": True})
            )

            async def reader() -> None:
                async for msg in ws:
                    if isinstance(msg, bytes):
                        continue
                    m = json.loads(msg)
                    frames.append(
                        m["type"] if m["type"] != "call_state" else f"call_state:{m['state']}"
                    )
                    if m["type"] == "tts_end":
                        await ws.send(json.dumps({"type": "playback_done"}))
                    if m["type"] == "answer":
                        result.update(m["result"])
                    if m["type"] == "error":
                        result["error"] = m

            task = asyncio.create_task(reader())
            while "tts_end" not in frames and "error" not in result and not task.done():
                await asyncio.sleep(0.1)
            audio = b"\x00\x00" * 8000 + pcm + b"\x00\x00" * 16000
            for i in range(0, len(audio), 1024):
                await ws.send(audio[i : i + 1024])
                await asyncio.sleep(0.032)  # real-time cadence
            await ws.send(json.dumps({"type": "commit"}))
            try:
                await asyncio.wait_for(task, 30)
            except TimeoutError:
                task.cancel()
    print("observed in sim:", seen, "| answer spoken:", phrase)
    print("frames:", " ".join(frames))
    if "error" in result:
        print("error:", result["error"])
        return 1
    obs = result.get("observation") or {}
    print("recorded outcome:", obs.get("outcome"), "| modality:", obs.get("modality"))  # type: ignore[union-attr]
    return 0 if obs.get("outcome") == seen else 1  # type: ignore[union-attr]


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
