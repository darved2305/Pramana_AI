"""Per-question media session: speak the question, stream the answer to Prisma, submit it.

One WebSocket per pending question (``WS /v1/investigations/{id}/questions/{qid}/media``). The
session opens its own Prisma v3.0 realtime session with that question's context (the
participant's language candidates, ``codemix``, the probe's answer vocabulary as keyterms,
``x-min-segment-ms`` 100 so a one-word "haan" is kept), which keeps every session far below
Gnani's 15-minute cap. The first non-empty final transcript goes through exactly the same
extraction and engine path as a typed or uploaded voice answer.

Protocol (JSON text frames unless noted):

Client -> server
    {"type": "start", "token": "<participant token>", "play_question": true}   (first, <= 10 s)
    binary: PCM s16le, 16 kHz, mono, any chunk size up to 64 KiB (re-framed to 1,024 bytes)
    {"type": "commit"}            end of the answer (push-to-talk release); flushes Prisma
    {"type": "tap_answer", "outcome": "no"}   answer without speech (accessibility)
    {"type": "playback_done"}     optional; the question audio finished playing
    {"type": "stop"}              hang up without answering

Server -> client
    {"type": "ready", "question_id", "participant_id", "text", "language", "outcomes",
     "model_confirmed"}
    {"type": "tts_start", "utt_id": 1, "format": "wav", "bytes": N, "cached": bool}
    binary: the question audio (WAV), in chunks of at most 16 KiB
    {"type": "tts_end", "utt_id": 1}
    {"type": "speech_start"} / {"type": "processing"}
    {"type": "transcript", "text", "detected_language", "provider_latency_ms"}
    {"type": "empty_transcript"}  nothing recognised: nothing recorded, keep talking
    {"type": "answer", "result": AnswerResult}   then the socket closes with 1000
    {"type": "error", "code", "message", "status", "fatal"}   fatal errors close the socket
    {"type": "call_state", "state", "event", "utt_id"}   every call-runtime transition
    {"type": "stop_playback", "utt_id"}   the participant started speaking over the question
    {"type": "reprompt", "utt_id", "text"}   silence: the question is asked once more

The session is driven by the call runtime (``calls/runtime.py``, PLAN section 12). Opening the
socket from the participant page means the call was accepted and consent given, so it starts
in ``ASKING``. ``playback_done`` (or the end of the question audio, if the client never says
so) moves it to ``LISTENING``; speech during ``ASKING`` is barge-in. After ``reprompt_s`` of
silence the question is asked once more; after ``unavailable_s`` the session ends with
``PARTICIPANT_SILENT`` (close 4408) and the question stays pending.

Close codes: 1000 answered or stopped, 4400 bad protocol, 4401 bad token, 4403 wrong
participant, 4404 not found, 4408 participant silent or session time limit, 4409 question no
longer pending or session already open, 4429 voice limits (streams, rate, budget), 4503 voice
not configured, 1011 upstream failure.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from pramana_contracts import Modality, SubmitAnswer
from pramana_contracts.tokens import TokenError

from ..calls.runtime import CallEvent, CallSession, CallState, CallTimers
from ..errors import ApiError
from ..investigations import InvestigationService, PendingQuestion
from ..observability import log
from ..runtime.broadcast import EventBroadcaster
from ..visibility import for_participant
from .conversation import QuestionAudioCache, answer_keyterms, speak_question, stt_options
from .gnani import GnaniClient, GnaniSttStream

START_TIMEOUT_S = 10.0
TTS_CHUNK = 16 * 1024
MAX_CLIENT_FRAME = 64 * 1024
COMMIT_WAIT_S = 6.0
CALL_TIMERS = CallTimers()
"""Silence timers for media sessions (tests shorten them)."""
PLAYBACK_GRACE_S = 1.0
"""Extra time after the question audio's length before assuming it finished playing."""
TIMER_POLL_S = 0.25


def close_code_for(status: int) -> int:
    return {
        400: 4400,
        401: 4401,
        403: 4403,
        404: 4404,
        408: 4408,
        409: 4409,
        413: 4400,
        422: 4400,
        429: 4429,
        503: 4503,
    }.get(status, 1011)


class MediaClosedError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


@dataclass
class ActiveSessions:
    """One open media session per participant token (``jti``): a copied link cannot listen in."""

    jtis: set[str] = field(default_factory=set)


class MediaSession:
    def __init__(
        self,
        ws: WebSocket,
        inv_id: str,
        question_id: str,
        svc: InvestigationService,
        gnani: GnaniClient,
        cache: QuestionAudioCache,
        broadcaster: EventBroadcaster,
        active: ActiveSessions,
        max_s: float,
        *,
        call: CallSession | None = None,
        send_lock: asyncio.Lock | None = None,
    ) -> None:
        self.ws, self.inv_id, self.question_id = ws, inv_id, question_id
        self.svc, self.gnani, self.cache = svc, gnani, cache
        self.broadcaster, self.active, self.max_s = broadcaster, active, max_s
        self.in_call = call is not None
        """Part of a participant call (``voice/call.py``): the call owns ringing, consent and
        hang-up; this session runs one question turn and returns to IDLE."""
        self.call = call or CallSession(
            call_id=f"{inv_id}:{question_id}", participant_id="", timers=CALL_TIMERS
        )
        self.played_until: float | None = None
        """Monotonic time by which the question audio has surely finished playing."""
        self.spoken: bytes | None = None
        self.submitting = False
        self.done = asyncio.Event()
        self._send_lock = send_lock or asyncio.Lock()

    # -- sending ---------------------------------------------------------------------------

    async def send(self, msg: dict[str, Any]) -> None:
        async with self._send_lock:
            await self.ws.send_text(json.dumps(msg, ensure_ascii=False))

    async def send_bytes(self, data: bytes) -> None:
        async with self._send_lock:
            await self.ws.send_bytes(data)

    async def fail(self, exc: ApiError, *, fatal: bool = True) -> None:
        with contextlib.suppress(Exception):
            await self.send(
                {
                    "type": "error",
                    "code": exc.code,
                    "message": exc.message,
                    "status": exc.status,
                    "fatal": fatal,
                }
            )
        if fatal:
            raise MediaClosedError(close_code_for(exc.status))

    async def fire(self, event: CallEvent) -> None:
        """Apply a call-runtime event (if legal now) and tell the client the new state."""
        if not self.call.can(event):
            return
        t = self.call.fire(event)
        if t.target != CallState.ASKING:
            self.played_until = None
        with contextlib.suppress(Exception):
            await self.send(
                {
                    "type": "call_state",
                    "state": t.target.value,
                    "event": t.event.value,
                    "utt_id": t.utterance,
                }
            )

    async def _hang_up(self, event: CallEvent) -> None:
        await self.fire(event)
        await self.fire(CallEvent.CLOSE)
        await self.fire(CallEvent.CLOSED)

    # -- lifecycle ---------------------------------------------------------------------------

    async def run(self) -> None:
        await self.ws.accept()
        code = 1000
        jti: str | None = None
        try:
            start = await self._start()
            claims = self._authenticate(str(start.get("token", "")))
            q = await self._question(claims.sub, claims.scn)
            if claims.jti in self.active.jtis:
                await self.fail(ApiError(409, "MEDIA_SESSION_ACTIVE", "already connected"))
            jti = claims.jti
            self.active.jtis.add(jti)
            self.call.participant_id = q.participant.id
            await self._converse(q, bool(start.get("play_question", True)))
        except MediaClosedError as exc:
            code = exc.code
        except WebSocketDisconnect:
            if self.call.can(CallEvent.DISCONNECTED):
                self.call.fire(CallEvent.DISCONNECTED)
            return
        finally:
            if jti is not None:
                self.active.jtis.discard(jti)
        with contextlib.suppress(Exception):
            await self.ws.close(code=code)

    async def _start(self) -> dict[str, Any]:
        try:
            raw = await asyncio.wait_for(self.ws.receive_text(), START_TIMEOUT_S)
            msg = json.loads(raw)
        except (TimeoutError, json.JSONDecodeError, KeyError):
            msg = None
        if not isinstance(msg, dict) or msg.get("type") != "start":
            await self.fail(ApiError(400, "MEDIA_EXPECTED_START", "first message must be start"))
        assert isinstance(msg, dict)
        return msg

    def _authenticate(self, token: str) -> Any:
        try:
            return self.svc.verify_participant_token(token)
        except TokenError as exc:
            raise MediaClosedError(4401) from exc

    async def _question(self, participant_id: str, scenario_id: str) -> PendingQuestion:
        try:
            q = await self.svc.pending_question(self.inv_id, self.question_id, participant_id)
        except ApiError as exc:
            await self.fail(exc)
            raise  # unreachable: fail() raises
        if q.scenario_id != scenario_id:
            await self.fail(ApiError(403, "WRONG_INVESTIGATION", "token is for another scenario"))
        return q

    async def turn(self, q: PendingQuestion, play: bool) -> None:
        """One question turn inside a participant call (the call is already ASKING)."""
        await self._converse(q, play)

    async def _converse(self, q: PendingQuestion, play: bool) -> None:
        langs, codemix = stt_options(q.participant)
        try:
            async with self.gnani.stream(
                langs,
                codemix=codemix,
                keyterms=answer_keyterms(q.pack, q.probe_id),
                min_segment_ms=100,
            ) as upstream:
                await self.send(
                    {
                        "type": "ready",
                        "question_id": q.id,
                        "participant_id": q.participant.id,
                        "text": q.text,
                        "language": q.language,
                        "outcomes": list(q.pack.probe_by_id[q.probe_id].outcomes),
                        "model_confirmed": upstream.model_confirmed,
                    }
                )
                self.call.start_question(q.id)
                if not self.in_call:
                    await self.fire(CallEvent.ACCEPTED)
                    await self.fire(CallEvent.CONSENT_YES)  # -> ASKING
                if play:
                    await self._speak(q)
                if self.played_until is None:
                    await self.fire(CallEvent.TTS_DONE)  # nothing to play: listen now
                await self._pump(q, upstream)
        except ApiError as exc:  # no stream slot, over budget, not configured, Gnani refused
            await self.fail(exc)

    async def _speak(self, q: PendingQuestion) -> None:
        """Send the question audio. A TTS failure is not fatal: the text is on screen."""
        try:
            audio, cached = await speak_question(self.gnani, self.cache, q.text, q.language)
        except ApiError as exc:
            await self.fail(exc, fatal=False)
            return
        await self._send_audio(audio, cached)

    async def _send_audio(self, audio: bytes, cached: bool) -> None:
        self.spoken = audio
        utt = self.call.utterance
        self.played_until = time.monotonic() + _wav_seconds(audio) + PLAYBACK_GRACE_S
        await self.send(
            {
                "type": "tts_start",
                "utt_id": utt,
                "format": "wav",
                "bytes": len(audio),
                "cached": cached,
            }
        )
        for i in range(0, len(audio), TTS_CHUNK):
            await self.send_bytes(audio[i : i + TTS_CHUNK])
        await self.send({"type": "tts_end", "utt_id": utt})

    # -- the answer ----------------------------------------------------------------------------

    async def _pump(self, q: PendingQuestion, upstream: GnaniSttStream) -> None:
        tasks = {
            asyncio.create_task(self._from_client(q, upstream), name="client"),
            asyncio.create_task(self._from_upstream(q, upstream), name="upstream"),
            asyncio.create_task(self._watch(q), name="watch"),
            asyncio.create_task(self._timers(q), name="timers"),
        }
        try:
            done, _ = await asyncio.wait(
                tasks, timeout=self.max_s, return_when=asyncio.FIRST_COMPLETED
            )
            if not done:
                await self.fail(ApiError(408, "MEDIA_SESSION_TIMEOUT", "session time limit"))
            for t in done:
                exc = t.exception()
                if exc is not None:
                    raise exc
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t

    async def _from_client(self, q: PendingQuestion, upstream: GnaniSttStream) -> None:
        while True:
            msg = await self.ws.receive()
            if msg["type"] == "websocket.disconnect":
                raise WebSocketDisconnect(msg.get("code", 1000))
            data = msg.get("bytes")
            if data is not None:
                if len(data) > MAX_CLIENT_FRAME or len(data) % 2:
                    await self.fail(ApiError(400, "MEDIA_BAD_FRAME", "frames are PCM16, <= 64 KiB"))
                await upstream.send_pcm(data)
                continue
            try:
                ctl = json.loads(msg.get("text") or "")
            except json.JSONDecodeError:
                await self.fail(ApiError(400, "MEDIA_BAD_MESSAGE", "not JSON"))
                continue
            kind = ctl.get("type") if isinstance(ctl, dict) else None
            if kind == "commit":
                await upstream.commit()
            elif kind == "tap_answer":
                outcome = str(ctl.get("outcome", ""))
                await self._submit(q, outcome=outcome)
                return
            elif kind == "stop":
                await self._hang_up(CallEvent.LATER)
                return
            elif kind == "playback_done":
                if self.call.state == CallState.ASKING:
                    await self.fire(CallEvent.TTS_DONE)
                continue
            else:
                await self.fail(ApiError(400, "MEDIA_BAD_MESSAGE", f"unknown type {kind!r}"))

    async def _from_upstream(self, q: PendingQuestion, upstream: GnaniSttStream) -> None:
        async for ev in upstream.events():
            if ev.type in ("speech_start", "processing"):
                if ev.type == "speech_start":
                    await self._heard_speech()
                await self.send({"type": ev.type})
            elif ev.type == "transcript":
                text = str(ev.raw.get("text", "")).strip()
                if not text:
                    # Empty or pure noise: no evidence, the question stays pending.
                    await self.send({"type": "empty_transcript"})
                    continue
                latency = ev.raw.get("latency")
                await self.send(
                    {
                        "type": "transcript",
                        "text": text,
                        "detected_language": ev.raw.get("detected_language_code"),
                        "provider_latency_ms": float(latency) if latency is not None else None,
                    }
                )
                await self._heard_speech()
                await self.fire(CallEvent.FINAL_TRANSCRIPT)
                await self._submit(q, text=text[:1000])
                return
            elif ev.type == "error":
                await self.fail(
                    ApiError(502, "VOICE_PROVIDER_ERROR", str(ev.raw.get("message", "")))
                )
            elif ev.type == "closed":
                await self.fail(
                    ApiError(502, "VOICE_STREAM_CLOSED", f"upstream closed ({ev.raw.get('code')})")
                )

    async def _heard_speech(self) -> None:
        if self.call.state == CallState.ASKING:
            utt = self.call.utterance
            await self.fire(CallEvent.BARGE_IN)
            await self.send({"type": "stop_playback", "utt_id": utt})
        self.call.heard_speech()

    async def _timers(self, q: PendingQuestion) -> None:
        """Playback end, one re-prompt after silence, and giving up on a silent participant."""
        while True:
            await asyncio.sleep(TIMER_POLL_S)
            if self.submitting:
                continue
            if self.call.state == CallState.ASKING:
                if self.played_until is not None and time.monotonic() >= self.played_until:
                    await self.fire(CallEvent.TTS_DONE)
                continue
            due = self.call.due()
            if due == CallEvent.SILENCE_REPROMPT:
                await self.fire(due)  # -> ASKING, a new utterance
                await self.send({"type": "reprompt", "utt_id": self.call.utterance, "text": q.text})
                if self.spoken is not None:
                    await self._send_audio(self.spoken, True)  # already paid for once
                else:
                    await self.fire(CallEvent.TTS_DONE)
            elif due == CallEvent.SILENCE_TIMEOUT:
                await self.fire(due)
                await self.fire(CallEvent.CLOSED)
                await self.fail(
                    ApiError(408, "PARTICIPANT_SILENT", "no answer was heard; ask again later")
                )

    async def _watch(self, q: PendingQuestion) -> None:
        """End the session if the question is answered or withdrawn elsewhere."""
        with self.broadcaster.subscribe(self.inv_id) as sub:
            while True:
                await sub.wait(5.0)
                if self.submitting:
                    continue
                try:
                    await self.svc.pending_question(self.inv_id, q.id, q.participant.id)
                except ApiError as exc:
                    if self.submitting:
                        continue
                    if self.in_call and self.call.can(CallEvent.PREEMPT):
                        # In a call, a withdrawn question ends this turn, not the call.
                        await self.fire(CallEvent.PREEMPT)
                        await self.send({"type": "question_withdrawn", "question_id": q.id})
                        return
                    await self.fail(exc)

    async def _submit(
        self, q: PendingQuestion, *, text: str | None = None, outcome: str | None = None
    ) -> None:
        self.submitting = True
        started = time.perf_counter()
        try:
            result = await self.svc.answer(
                self.inv_id,
                SubmitAnswer(
                    question_id=q.id,
                    participant_id=q.participant.id,
                    text=text,
                    outcome=outcome,
                    modality=Modality.VOICE if text is not None else Modality.TEXT,
                ),
            )
        except ApiError as exc:
            await self.fail(exc)
            return
        except ValueError as exc:  # SubmitAnswer validation
            await self.fail(ApiError(422, "INVALID_ANSWER", str(exc)))
            return
        log.info(
            "media_answer",
            investigation_id=self.inv_id,
            question_id=q.id,
            via="speech" if text is not None else "tap",
            ms=round((time.perf_counter() - started) * 1000),
        )
        shown = result.model_copy(update={"state": for_participant(result.state, q.participant.id)})
        await self.send({"type": "answer", "result": shown.model_dump(mode="json")})
        if self.in_call:
            await self.fire(CallEvent.OBSERVATION_PROPOSED)  # -> IDLE; the call asks next
        else:
            await self._hang_up(CallEvent.OBSERVATION_PROPOSED)


def _wav_seconds(audio: bytes) -> float:
    """Playing time of a 16-bit WAV from its byte count (Timbre headers hold a placeholder)."""
    if len(audio) < 44:
        return 0.0
    channels = int.from_bytes(audio[22:24], "little") or 1
    rate = int.from_bytes(audio[24:28], "little")
    if rate <= 0:
        return 0.0
    return (len(audio) - 44) / (2 * channels * rate)
