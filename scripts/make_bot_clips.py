"""Synthesise the voice bots' answers with Meta MMS-TTS (CC-BY-NC 4.0, internal testing only).

Writes ``<out>/<lang>__<value>.wav`` (16 kHz mono PCM16) for ``scripts/voice_bot_run.py``. Every
phrase is checked against the answer extractor first (``--check``), so a clip can only fail at
speech recognition. MMS is not a project dependency: run the synthesis in a throwaway environment
with torch (CPU), transformers and scipy (about 0.8 GB, docs/engineering/VOICE_SAMPLES.md) and
delete it afterwards.

Usage: python scripts/make_bot_clips.py --check          (project environment)
       python scripts/make_bot_clips.py <out dir>        (MMS environment)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PHRASES: dict[str, dict[str, str]] = {
    "hi": {
        "yes": "हाँ, चल रहा है",
        "no": "नहीं, कुछ नहीं चल रहा",
        "no_network": "वाईफाई दिख ही नहीं रहा",
        "stuck_connecting": "कनेक्टिंग पे अटका है",
        "connected": "कनेक्टेड है",
        "on": "हाँ, चालू है",
        "off": "नहीं, बंद है",
        "green": "हरी लाइट है",
        "amber": "नारंगी लाइट है",
        "red": "लाल लाइट है",
        "up": "ब्रेकर ऊपर है",
        "tripped": "ब्रेकर नीचे है",
        "AP_2A": "ए पी टू ए दिख रहा है",
        "AP_2B": "ए पी टू बी दिख रहा है",
        "not_connected": "कोई नहीं",
    },
    "mr": {
        "yes": "हो, चालू आहे",
        "no": "नाही, काहीच चालत नाही",
        "no_network": "वायफाय दिसतच नाही",
        "stuck_connecting": "कनेक्ट होतंय पण होत नाही",
        "connected": "कनेक्टेड आहे",
        "on": "हो, चालू आहे",
        "off": "नाही, बंद आहे",
        "green": "हिरवा दिवा आहे",
        "amber": "नारिंगी दिवा आहे",
        "red": "लाल दिवा आहे",
        "up": "ब्रेकर वर आहे",
        "tripped": "ब्रेकर खाली आहे",
        "AP_2A": "ए पी टू ए दिसत आहे",
        "AP_2B": "ए पी टू बी दिसत आहे",
        "not_connected": "एकही नाही",
    },
}
VOICES = {"hi": "facebook/mms-tts-hin", "mr": "facebook/mms-tts-mar"}


def check() -> int:
    """Every phrase must extract to its own value for every probe that can have that value."""
    from pramana_core.language.extraction import RuleExtractor
    from pramana_domain import load_pack

    extractor, bad = RuleExtractor(), 0
    for lang, table in PHRASES.items():
        for probe in load_pack("campus_block_c").probes:
            for outcome in probe.outcomes:
                got = extractor.extract_sync(table[outcome], list(probe.outcomes)).outcome
                if got != outcome:
                    bad += 1
                    print(f"{lang} {probe.id}: {table[outcome]!r} -> {got}, expected {outcome}")
    print(f"{bad} phrase(s) do not extract to their value")
    return 1 if bad else 0


def synthesise(out: Path) -> None:
    import numpy as np
    import scipy.io.wavfile as wavfile
    import torch
    from transformers import AutoTokenizer, VitsModel

    out.mkdir(parents=True, exist_ok=True)
    for lang, voice in VOICES.items():
        tok = AutoTokenizer.from_pretrained(voice)
        model = VitsModel.from_pretrained(voice)
        rate = model.config.sampling_rate
        for value, text in PHRASES[lang].items():
            torch.manual_seed(7)
            with torch.no_grad():
                wave = model(**tok(text, return_tensors="pt")).waveform[0].numpy()
            raw = out / f"{lang}__{value}.raw.wav"
            wavfile.write(raw, rate, (np.clip(wave, -1, 1) * 32767).astype(np.int16))
            final = out / f"{lang}__{value}.wav"
            subprocess.run(
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(raw),
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-sample_fmt",
                    "s16",
                    str(final),
                ],
                check=True,
            )
            raw.unlink()
            print(final.name)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    if sys.argv[1] == "--check":
        sys.exit(check())
    synthesise(Path(sys.argv[1]))
