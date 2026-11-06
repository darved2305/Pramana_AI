"""Voice turn helpers: speak a planned question, and hear the answer with question context.

The voice layer adds no decisions. A spoken answer becomes a transcript, the transcript goes
through the same extractor as typed answers, and the engine updates exactly as it would for text.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import os
import struct
import wave
from collections import OrderedDict
from pathlib import Path

from pramana_contracts import ParticipantSpec, TemplateLanguage
from pramana_domain import DomainPack

from ..errors import ApiError
from ..language.extraction import OUTCOME_LEXICON
from ..language.speakable import speakable
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
    """Synthesised questions keyed by text, language and voice: a bounded memory cache, backed
    by an optional bounded directory so audio survives restarts.

    Question texts come from fixed templates, so the same question for the same person repeats
    across investigations: synthesis is paid once, and replaying it is free and instant.
    """

    def __init__(
        self,
        max_entries: int = 64,
        max_bytes: int = 4 * 1024 * 1024,
        *,
        disk_dir: Path | None = None,
        max_disk_files: int = 500,
    ) -> None:
        self._items: OrderedDict[str, bytes] = OrderedDict()
        self._max_entries, self._max_bytes, self._bytes = max_entries, max_bytes, 0
        self._dir, self._max_disk_files = disk_dir, max_disk_files
        if disk_dir is not None:
            disk_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(spoken_text: str, language: str, model: str, voice: str | None) -> str:
        return hashlib.sha256(f"{model}|{voice}|{language}|{spoken_text}".encode()).hexdigest()

    def get(self, key: str) -> bytes | None:
        audio = self._items.get(key)
        if audio is not None:
            self._items.move_to_end(key)
            return audio
        path = self._path(key)
        if path is None or not path.exists():
            return None
        try:
            audio = path.read_bytes()
            os.utime(path)  # recently used: evicted last
        except OSError:
            return None
        self._remember(key, audio)
        return audio

    def put(self, key: str, audio: bytes) -> None:
        if key in self._items or len(audio) > self._max_bytes:
            return
        self._remember(key, audio)
        path = self._path(key)
        if path is not None:
            with contextlib.suppress(OSError):  # a disk problem only loses the cache
                tmp = path.with_suffix(".tmp")
                tmp.write_bytes(audio)
                tmp.replace(path)
                self._evict_disk()

    def _path(self, key: str) -> Path | None:
        return None if self._dir is None else self._dir / f"{key}.wav"

    def _evict_disk(self) -> None:
        assert self._dir is not None
        files = sorted(self._dir.glob("*.wav"), key=lambda f: f.stat().st_mtime)
        for old in files[: max(0, len(files) - self._max_disk_files)]:
            with contextlib.suppress(OSError):
                old.unlink()

    def _remember(self, key: str, audio: bytes) -> None:
        self._items[key] = audio
        self._bytes += len(audio)
        while len(self._items) > self._max_entries or self._bytes > self._max_bytes:
            _, old = self._items.popitem(last=False)
            self._bytes -= len(old)

    def __len__(self) -> int:
        return len(self._items)

    @property
    def bytes_cached(self) -> int:
        return self._bytes


async def speak_question(
    gnani: GnaniClient, cache: QuestionAudioCache, text: str, language: TemplateLanguage
) -> tuple[bytes, bool]:
    """Return (WAV, served_from_cache). Cached audio costs no credits."""
    tts_lang = TTS_LANGUAGE[language]
    model = "timbre-v2.5" if tts_lang == "hi-en" else "timbre-v3.0"
    spoken_text = speakable(text, language)
    key = cache.key(spoken_text, tts_lang, model, None)
    cached = cache.get(key)
    if cached is not None:
        return cached, True
    audio, _ = await gnani.synthesize(spoken_text, language=tts_lang, model=model)
    cache.put(key, audio)
    return audio, False


STREAM_SAMPLE_RATE = 24_000
"""Sample rate of streamed question audio (PCM16 mono, the same rate as the REST WAV)."""


def pcm_to_wav(pcm: bytes, rate: int = STREAM_SAMPLE_RATE) -> bytes:
    """A correct WAV header (real data length) around PCM16 mono."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def streaming_wav_header(rate: int = STREAM_SAMPLE_RATE) -> bytes:
    """A PCM16 mono WAV header whose sizes say "until the end of the stream" (0xFFFFFFFF),
    for audio whose length is not known when the header is sent."""
    open_ended = 0xFFFFFFFF
    return (
        b"RIFF"
        + struct.pack("<I", open_ended)
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", open_ended)
    )


class QuestionAudio:
    """A question's audio, fetched in the background while the recognizer connects.

    Cached audio is ready at once as a WAV (``wav``, ``cached``). Otherwise Timbre streams it
    (``synthesize_stream``) and each PCM chunk is put on ``chunks`` as it arrives, so playback
    can start before synthesis finishes; the joined audio is then cached as a WAV. If the
    stream fails before its first chunk, one REST WAV is fetched instead. ``None`` on
    ``chunks`` marks the end; ``error`` holds a failure that left no playable audio.
    """

    def __init__(
        self, gnani: GnaniClient, cache: QuestionAudioCache, text: str, language: TemplateLanguage
    ) -> None:
        self.chunks: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.wav: bytes | None = None
        self.cached = False
        self.streamed = False
        self.error: ApiError | None = None
        self.task = asyncio.create_task(self._run(gnani, cache, text, language))

    async def _run(
        self, gnani: GnaniClient, cache: QuestionAudioCache, text: str, language: TemplateLanguage
    ) -> None:
        tts_lang = TTS_LANGUAGE[language]
        model = "timbre-v2.5" if tts_lang == "hi-en" else "timbre-v3.0"
        spoken_text = speakable(text, language)
        key = cache.key(spoken_text, tts_lang, model, None)
        try:
            hit = cache.get(key)
            if hit is not None:
                self.wav, self.cached = hit, True
                return
            pcm = bytearray()
            try:
                async with contextlib.aclosing(
                    gnani.synthesize_stream(
                        spoken_text, language=tts_lang, model=model, sample_rate=STREAM_SAMPLE_RATE
                    )
                ) as stream:
                    async for chunk in stream:
                        pcm += chunk
                        self.streamed = True
                        await self.chunks.put(chunk)
            except ApiError as exc:
                if self.streamed:
                    self.error = exc  # part was played; do not cache a cut-off question
                    return
                try:  # nothing was played: fall back to one WAV over REST
                    audio, _ = await gnani.synthesize(spoken_text, language=tts_lang, model=model)
                except ApiError as exc2:
                    self.error = exc2
                    return
                cache.put(key, audio)
                self.wav = audio
                return
            self.wav = pcm_to_wav(bytes(pcm))
            cache.put(key, self.wav)
        finally:
            await self.chunks.put(None)

    def cancel(self) -> None:
        if not self.task.done():
            self.task.cancel()


def stt_options(participant: ParticipantSpec) -> tuple[list[str], bool]:
    """(language candidates, codemix) from the participant's registered language profile."""
    langs = [str(c) for c in participant.languages.stt_candidates]
    return langs, participant.languages.codemix
