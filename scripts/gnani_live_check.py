"""Live Gnani validation through the running core API (spends a few paise of credits).

Results are for the team only: the Gnani EULA (s.16, s.4.2(g)) bars publishing benchmark or
performance results for Gnani models. Audio is written to --out (outside the repository).

Usage: python scripts/gnani_live_check.py --out <dir> [--core http://127.0.0.1:8000]
       [--probe-concurrency]
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import time
import wave
from pathlib import Path

import httpx
import websockets

PHRASES = [
    ("mr-IN", ["mr-IN", "hi-IN"], "स्क्रीन बंद आहे"),
    ("hi-en", ["hi-IN", "en-IN"], "WiFi list mein NAVA WiFi dikh hi nahi raha"),
    ("hi-IN", ["hi-IN", "en-IN"], "ब्रेकर नंबर सात नीचे है"),
]


def to_16k_mono_pcm(wav_bytes: bytes) -> bytes:
    """Resample a 16-bit mono WAV to 16 kHz by linear interpolation (test client only)."""
    with wave.open(io.BytesIO(wav_bytes)) as w:
        rate, frames = w.getframerate(), w.readframes(w.getnframes())
    samples = memoryview(frames).cast("h")
    if rate == 16000:
        return frames
    n_out = int(len(samples) * 16000 / rate)
    out = bytearray()
    for i in range(n_out):
        pos = i * rate / 16000
        j = int(pos)
        frac = pos - j
        a = samples[j]
        b = samples[j + 1] if j + 1 < len(samples) else a
        out += int(a + (b - a) * frac).to_bytes(2, "little", signed=True)
    return bytes(out)


async def stream_once(core_ws: str, pcm: bytes, langs: list[str]) -> dict[str, object]:
    async with websockets.connect(core_ws, max_size=2**20) as ws:
        await ws.send(json.dumps({"type": "start", "language_code": langs}))
        ready = json.loads(await ws.recv())
        if ready.get("type") != "ready":
            return {"error": ready}
        silence = b"\x00\x00" * 8000  # 0.5 s lead-in
        audio = silence + pcm + b"\x00\x00" * 16000  # pad so server VAD sees end of speech
        for k in range(0, len(audio), 1024):  # real-time cadence: 32 ms per frame
            await ws.send(audio[k : k + 1024])
            await asyncio.sleep(0.032)
        sent_at = time.perf_counter()
        await ws.send(json.dumps({"type": "commit"}))
        result: dict[str, object] = {"model_confirmed": ready.get("model_confirmed")}
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            if msg["type"] == "transcript" and msg.get("text"):
                result |= {
                    "text": msg["text"],
                    "lang": msg.get("detected_language"),
                    "provider_latency_ms": msg.get("provider_latency_ms"),
                    "eos_to_transcript_ms": msg.get("end_of_speech_to_transcript_ms"),
                    "after_audio_end_ms": round((time.perf_counter() - sent_at) * 1000),
                }
                break
            if msg["type"] in ("error", "closed"):
                result["error"] = msg
                break
        await ws.send(json.dumps({"type": "stop"}))
        return result


async def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--core", default="http://127.0.0.1:8000")
    ap.add_argument("--out", required=True)
    ap.add_argument("--probe-concurrency", action="store_true")
    ap.add_argument(
        "--stream-only",
        action="store_true",
        help="reuse WAVs saved in --out by a previous run; only test streaming",
    )
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ws_url = args.core.replace("http", "ws", 1) + "/v1/voice/stream"

    async with httpx.AsyncClient(base_url=args.core, timeout=60) as c:
        ready = (await c.get("/ready")).json()
        print("ready:", ready["checks"])
        clips: list[tuple[str, list[str], str, bytes]] = []
        if args.stream_only:  # no TTS or REST spend: reuse audio saved by an earlier run
            clips = [
                (lang, cands, text, (out / f"tts_{lang}.wav").read_bytes())
                for lang, cands, text in PHRASES
                if (out / f"tts_{lang}.wav").exists()
            ]
        print("\n== TTS (Timbre) ==")
        for lang, cands, text in [] if args.stream_only else PHRASES:
            r = await c.post("/v1/voice/tts", json={"text": text, "language": lang})
            if r.status_code != 200:
                print(f"  {lang}: HTTP {r.status_code} {r.text[:200]}")
                continue
            (out / f"tts_{lang}.wav").write_bytes(r.content)
            # Gnani's streamed WAV header declares a placeholder length; count the bytes.
            with wave.open(io.BytesIO(r.content)) as w:
                rate = w.getframerate()
            dur = (len(r.content) - 44) / (2 * rate)
            print(
                f"  {lang}: {len(text)} chars -> {dur:.2f} s audio, "
                f"wall {r.headers.get('X-TTS-Wall-Ms')} ms  [{text}]"
            )
            clips.append((lang, cands, text, r.content))

        print("\n== STT REST (Prisma v3.0) on the synthesized audio ==")
        for lang, cands, text, audio in [] if args.stream_only else clips:
            r = await c.post(
                "/v1/voice/stt",
                files={"audio": ("q.wav", audio, "audio/wav")},
                data={"language_codes": ",".join(cands), "codemix": str(lang == "hi-en").lower()},
            )
            body = r.json()
            if r.status_code != 200:
                print(f"  {lang}: HTTP {r.status_code} {body}")
                continue
            print(
                f"  {lang}: model={body['model']} detected={body['detected_language']} "
                f"provider={body['provider_latency_ms']} ms wall={body['wall_ms']:.0f} ms"
            )
            print(f"      said : {text}\n      heard: {body['transcript']}")

        print("\n== STT realtime stream via /v1/voice/stream ==")
        for lang, cands, _text, audio in clips[:2]:
            res = await stream_once(ws_url, to_16k_mono_pcm(audio), cands)
            print(f"  {lang}: {res}")

        if args.probe_concurrency and clips:
            print("\n== Concurrency probes ==")
            _, cands, _, audio = clips[0]
            pcm = to_16k_mono_pcm(audio)
            results = await asyncio.gather(
                *[stream_once(ws_url, pcm, cands) for _ in range(3)], return_exceptions=True
            )
            ok = sum(1 for r in results if isinstance(r, dict) and "text" in r)
            print(
                f"  3 simultaneous streams: {ok} transcribed; "
                f"{[r if not isinstance(r, dict) else r.get('error') for r in results]}"
            )

        usage = (await c.get("/v1/voice/usage")).json()
        print("\n== Metered usage today ==")
        print(json.dumps({k: usage[k] for k in ("spent_today_inr", "by_service")}, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
