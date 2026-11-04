"""Voice turn helpers: speak a planned question, and hear the answer with question context.

The voice layer adds no decisions. A spoken answer becomes a transcript, the transcript goes
through the same extractor as typed answers, and the engine updates exactly as it would for text.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict

from pramana_contracts import ParticipantSpec, TemplateLanguage
from pramana_domain import DomainPack

from ..language.extraction import OUTCOME_LEXICON
from .gnani import GnaniClient

TTS_LANGUAGE: dict[TemplateLanguage, str] = {
    "en": "en-IN",
    "hi": "hi-IN",
    "mr": "mr-IN",
    "hi-en": "hi-en",
}
MAX_KEYTERMS = 200  # Prisma v3.0 limit


def answer_keyterms(pack: DomainPack, probe_id: str) -> list[str]:
    """Vocabulary a correct answer to this probe is likely to contain (question-conditioned ASR).

    Multi-word phrases come first because they carry the most context. The names on the
    equipment the question mentions are included so they are not misheard as other words.
    """
    probe = pack.probe_by_id[probe_id]
    terms: list[str] = []
    for outcome in probe.outcomes:
        phrases = sorted(OUTCOME_LEXICON.get(outcome, []), key=len, reverse=True)
        terms.extend(" ".join(p) for p in phrases)
    if probe.kind in ("wifi_status", "internet_works", "web_by_ip"):
        terms.append("NAVA-WiFi")
    seen: set[str] = set()
    out = []
    for t in terms:
        if t and t not in seen and "<|" not in t and "|>" not in t:
            seen.add(t)
            out.append(t)
    return out[:MAX_KEYTERMS]


class QuestionAudioCache:
    """Bounded in-memory cache of synthesised questions keyed by text, language and voice."""

    def __init__(self, max_entries: int = 64, max_bytes: int = 32 * 1024 * 1024) -> None:
        self._items: OrderedDict[str, bytes] = OrderedDict()
        self._max_entries, self._max_bytes, self._bytes = max_entries, max_bytes, 0

    @staticmethod
    def key(text: str, language: str, model: str, voice: str | None) -> str:
        return hashlib.sha256(f"{model}|{voice}|{language}|{text}".encode()).hexdigest()

    def get(self, key: str) -> bytes | None:
        audio = self._items.get(key)
        if audio is not None:
            self._items.move_to_end(key)
        return audio

    def put(self, key: str, audio: bytes) -> None:
        if key in self._items or len(audio) > self._max_bytes:
            return
        self._items[key] = audio
        self._bytes += len(audio)
        while len(self._items) > self._max_entries or self._bytes > self._max_bytes:
            _, old = self._items.popitem(last=False)
            self._bytes -= len(old)

    def __len__(self) -> int:
        return len(self._items)


async def speak_question(
    gnani: GnaniClient, cache: QuestionAudioCache, text: str, language: TemplateLanguage
) -> tuple[bytes, bool]:
    """Return (WAV, served_from_cache). Cached audio costs no credits."""
    tts_lang = TTS_LANGUAGE[language]
    model = "timbre-v2.5" if tts_lang == "hi-en" else "timbre-v3.0"
    key = cache.key(text, tts_lang, model, None)
    cached = cache.get(key)
    if cached is not None:
        return cached, True
    audio, _ = await gnani.synthesize(text, language=tts_lang, model=model)
    cache.put(key, audio)
    return audio, False


def stt_options(participant: ParticipantSpec) -> tuple[list[str], bool]:
    """(language candidates, codemix) from the participant's registered language profile."""
    langs = [str(c) for c in participant.languages.stt_candidates]
    return langs, participant.languages.codemix
