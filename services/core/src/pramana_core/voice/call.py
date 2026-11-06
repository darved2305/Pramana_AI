"""A participant's call: one WebSocket that rings, asks consent, then asks question after question.

``WS /v1/investigations/{id}/participants/{pid}/call``. The call runtime (``calls/runtime.py``)
drives it: ``RINGING -> CONSENT -> ASKING ... -> IDLE -> ASKING ... -> CLOSING -> ENDED``. Each
question is one turn of the per-question media session (``voice/media.py``) with its own Prisma
session and context, sharing this socket and state machine. Between turns the call waits in
``IDLE`` for the engine to address another question to this person.

Consent is explicit and logged (PRODUCT.md, "Consent"). Anything but a yes, saying "later", or
silence takes the person out of the investigation (``record_consent``): their pending question
is cancelled and the engine asks someone else.

Protocol (in addition to the per-question frames in ``voice/media.py``):

Client -> server
    {"type": "start", "token": "<participant token>", "play": true}      first, <= 10 s
    {"type": "accept"} / {"type": "decline"}                             answer the ring
    {"type": "consent", "answer": "yes" | "no" | "later"}
    then, per question, the media frames (PCM16, commit, tap_answer, playback_done, stop)

Server -> client
    {"type": "ringing", "participant_id", "language"}
    {"type": "consent_request", "text", "language"}       (and the consent audio if ``play``)
    per question: ready, tts_*, speech_start, transcript, answer, call_state...
    {"type": "idle", "waiting_s"}   every 15 s while waiting for the next question
    {"type": "call_end", "reason"}   then the socket closes (1000, or 4408 when silent)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
import uuid
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from pramana_contracts import ANSWERABLE_STATUSES, TemplateLanguage
from pramana_contracts.tokens import TokenError

from ..calls.runtime import CallEvent, CallSession, CallState
from ..errors import ApiError
from ..investigations import InvestigationService
from ..observability import log
from ..runtime.broadcast import EventBroadcaster
from .conversation import QuestionAudioCache, speak_question
from .gnani import GnaniClient
from .media import (
    CALL_TIMERS,
    START_TIMEOUT_S,
    ActiveSessions,
    MediaClosedError,
    MediaSession,
    close_code_for,
)

CONSENT_TEXT: dict[str, str] = {
    "en": "Hello, this is Pramana, helping fix a Wi-Fi and power problem in your building. "
    "Is it OK to ask you two or three quick questions? You can say no.",
    "hi": "नमस्ते, मैं प्रमाण हूँ, आपकी बिल्डिंग में वाई-फ़ाई और बिजली की समस्या ठीक करने में "
    "मदद कर रहा हूँ। क्या मैं आपसे दो-तीन छोटे सवाल पूछ सकता हूँ? आप मना कर सकते हैं।",
    "hi-en": "Namaste, main Pramana hoon, building ki WiFi aur power problem theek karne mein "
    "madad kar raha hoon. Kya main aapse do-teen chhote sawaal pooch sakta hoon? Aap mana "
    "kar sakte hain.",
    "mr": "नमस्कार, मी प्रमाण, तुमच्या इमारतीतील वाय-फाय आणि वीजेची अडचण सोडवायला मदत करतोय. "
    "मी तुम्हाला दोन-तीन छोटे प्रश्न विचारू का? तुम्ही नाही म्हणू शकता.",
}
"""The consent line from PRODUCT.md ("Is it OK to ask you two quick questions? You can say no.")."""

IDLE_WAIT_S = 120.0
"""How long the call waits in IDLE for the engine to ask this person something else."""
HEARTBEAT_S = 15.0
"""While waiting, send ``{"type": "idle"}`` this often. Proxies close silent sockets (Cloudflare
after about 100 s). The receive loop also detects a participant who hangs up while idle."""


class ParticipantCall:
    def __init__(
        self,
        ws: WebSocket,
        inv_id: str,
        participant_id: str,
        svc: InvestigationService,
        gnani: GnaniClient,
        cache: QuestionAudioCache,
        broadcaster: EventBroadcaster,
        active: ActiveSessions,
        max_s: float,
    ) -> None:
        self.ws, self.inv_id, self.participant_id = ws, inv_id, participant_id
        self.svc, self.gnani, self.cache = svc, gnani, cache
        self.broadcaster, self.active, self.max_s = broadcaster, active, max_s
        self.call = CallSession(
            call_id=f"{inv_id}:{participant_id}", participant_id=participant_id, timers=CALL_TIMERS
        )
        self.send_lock = asyncio.Lock()
        self.play = True
        self.questions = 0
        self.call_session_id = uuid.uuid4().hex

    async def send(self, msg: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.ws.send_text(json.dumps(msg, ensure_ascii=False))

    async def fire(self, event: CallEvent) -> None:
        if not self.call.can(event):
            return
        t = self.call.fire(event)
        with contextlib.suppress(Exception):
            await self.send(
                {
                    "type": "call_state",
                    "state": t.target.value,
                    "event": t.event.value,
                    "utt_id": t.utterance,
                }
            )

    # -- lifecycle --------------------------------------------------------------------------

    async def run(self) -> None:
        await self.ws.accept()
        code, jti, reason = 1000, None, "ended"
        disconnected = False
        socket_close_reason = ""
        call_end_sent = False
        try:
            start = await self._receive("start", START_TIMEOUT_S)
            try:
                claims = self.svc.verify_participant_token(str(start.get("token", "")))
            except TokenError as exc:
                raise MediaClosedError(4401) from exc
            if claims.sub != self.participant_id:
                await self._fail(ApiError(403, "WRONG_PARTICIPANT", "token is for someone else"))
            state = await self.svc.get(self.inv_id)
            if await self.svc.scenario_of(self.inv_id) != claims.scn:
                await self._fail(ApiError(403, "WRONG_INVESTIGATION", "token is for another one"))
            if claims.jti in self.active.jtis:
                await self._fail(ApiError(409, "MEDIA_SESSION_ACTIVE", "already connected"))
            jti = claims.jti
            self.active.jtis.add(jti)
            self.play = bool(start.get("play", True))
            me = next(p for p in state.participants if p.id == self.participant_id)
            language = me.languages.template_language
            reason = await self._converse(language)
        except MediaClosedError as exc:
            code = exc.code
            reason = "silent" if exc.code == 4408 else "error"
            if exc.code == 4408:
                await self._release("no answer during the call")
        except WebSocketDisconnect as exc:
            code = exc.code
            socket_close_reason = str(getattr(exc, "reason", ""))
            self.call.disconnect_code = code
            self.call.disconnect_reason = socket_close_reason
            reason = "participant disconnected"
            disconnected = True
            if self.call.can(CallEvent.DISCONNECTED):
                self.call.fire(CallEvent.DISCONNECTED)
        except Exception:
            code, reason = 1011, "error"
            raise
        finally:
            if jti is not None:
                self.active.jtis.discard(jti)
            if self.call.disconnect_code is not None:
                code = self.call.disconnect_code
                socket_close_reason = self.call.disconnect_reason
                reason = "participant disconnected"
                disconnected = True
                if self.call.can(CallEvent.DISCONNECTED):
                    self.call.fire(CallEvent.DISCONNECTED)
            task = asyncio.current_task()
            if task is not None and task.cancelling() and not disconnected:
                code, reason = 1011, "call handler cancelled"
            elif not disconnected:
                try:
                    await self.send({"type": "call_end", "reason": reason})
                    call_end_sent = True
                except Exception:
                    pass
                with contextlib.suppress(Exception):
                    await self.ws.close(code=code, reason=socket_close_reason)
            log.info(
                "call_ended",
                investigation_id=self.inv_id,
                participant_id=self.participant_id,
                call_session_id=self.call_session_id,
                reason=reason,
                questions=self.questions,
                socket_close_code=code,
                socket_close_reason=socket_close_reason,
                socket_close_initiator="participant" if disconnected else "server",
                call_end_sent=call_end_sent,
            )

    async def _converse(self, language: TemplateLanguage) -> str:
        await self.send(
            {
                "type": "ringing",
                "participant_id": self.participant_id,
                "language": language,
                "call_session_id": self.call_session_id,
            }
        )
        ring = await self._receive_ring()
        if ring != "accept":
            await self.fire(CallEvent.DECLINED if ring == "decline" else CallEvent.RING_TIMEOUT)
            await self.fire(CallEvent.CLOSED)
            await self._release("did not take the call")
            return "not answered"
        await self.fire(CallEvent.ACCEPTED)  # -> CONSENT
        text = CONSENT_TEXT.get(language, CONSENT_TEXT["en"])
        await self.send({"type": "consent_request", "text": text, "language": language})
        if self.play:
            await self._speak(text, language)
        consent = await self._receive("consent", float(CALL_TIMERS.ring_s))
        answer = str(consent.get("answer", "no"))
        await self.svc.record_consent(
            self.inv_id, self.participant_id, answer == "yes", f"consent: {answer}"
        )
        if answer != "yes":
            await self.fire(CallEvent.LATER if answer == "later" else CallEvent.CONSENT_NO)
            await self.fire(CallEvent.CLOSED)
            return "declined" if answer != "later" else "later"
        await self.fire(CallEvent.CONSENT_YES)  # -> ASKING
        return await self._questions()

    async def _questions(self) -> str:
        while True:
            q = await self._next_question()
            if q is None:
                if self.call.state == CallState.CLOSING:
                    await self.fire(CallEvent.CLOSED)
                    await self._release("said later")
                    return "later"
                if self.call.state == CallState.PREEMPTING:
                    await self.fire(CallEvent.NO_QUESTION)
                else:
                    await self.fire(CallEvent.CLOSE)
                await self.fire(CallEvent.CLOSED)
                return "nothing more to ask"
            if self.call.state == CallState.IDLE:
                await self.fire(CallEvent.ASK)
            elif self.call.state == CallState.PREEMPTING:
                await self.fire(CallEvent.NEW_QUESTION)
            turn = MediaSession(
                self.ws,
                self.inv_id,
                q.id,
                self.svc,
                self.gnani,
                self.cache,
                self.broadcaster,
                self.active,
                self.max_s,
                call=self.call,
                send_lock=self.send_lock,
            )
            self.questions += 1
            await turn.turn(q, self.play)
            if self.call.ended or self.call.state == CallState.CLOSING:
                await self.fire(CallEvent.CLOSED)
                await self._release("said later")
                return "later"

    async def _next_question(self) -> Any:
        """The pending question addressed to this person, waiting up to ``IDLE_WAIT_S``."""
        started = time.monotonic()
        deadline = started + IDLE_WAIT_S
        beat = started
        with self.broadcaster.subscribe(self.inv_id) as sub:
            while True:
                now = time.monotonic()
                if now - beat >= HEARTBEAT_S:
                    beat = now
                    try:
                        await self.send({"type": "idle", "waiting_s": round(now - started)})
                    except Exception as exc:  # the participant is gone
                        raise WebSocketDisconnect(1006) from exc
                state = await self.svc.get(self.inv_id)
                if state.status not in ANSWERABLE_STATUSES:
                    return None
                pq = next(
                    (
                        q
                        for q in state.pending_questions
                        if q.action.participant_id == self.participant_id
                    ),
                    None,
                )
                if pq is not None:
                    try:
                        return await self.svc.pending_question(
                            self.inv_id, pq.id, self.participant_id
                        )
                    except ApiError as exc:
                        if exc.code != "QUESTION_NOT_PENDING":
                            raise
                        # Another call can answer while this lookup is in flight. The event
                        # broadcast and the next state read will pick up the updated schedule.
                        await self.send({"type": "question_withdrawn", "question_id": pq.id})
                        continue
                left = deadline - time.monotonic()
                if left <= 0 or self.call.state == CallState.PREEMPTING:
                    return None
                receive = asyncio.create_task(self.ws.receive())
                wake = asyncio.create_task(sub.wait(min(left, 5.0, HEARTBEAT_S)))
                try:
                    done, _ = await asyncio.wait(
                        (receive, wake), return_when=asyncio.FIRST_COMPLETED
                    )
                    if receive in done:
                        message = receive.result()
                        if message["type"] == "websocket.disconnect":
                            raise WebSocketDisconnect(
                                message.get("code", 1000), message.get("reason", "")
                            )
                        if message.get("text"):
                            with contextlib.suppress(json.JSONDecodeError):
                                control = json.loads(message["text"])
                                if isinstance(control, dict) and control.get("type") == "stop":
                                    await self.fire(CallEvent.LATER)
                                    return None
                finally:
                    for task in (receive, wake):
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(receive, wake, return_exceptions=True)

    # -- helpers ----------------------------------------------------------------------------

    async def _speak(self, text: str, language: TemplateLanguage) -> None:
        try:
            audio, cached = await speak_question(self.gnani, self.cache, text, language)
        except ApiError as exc:  # not fatal: the text is on screen
            await self.send(
                {
                    "type": "error",
                    "code": exc.code,
                    "message": exc.message,
                    "status": exc.status,
                    "fatal": False,
                }
            )
            return
        async with self.send_lock:
            await self.ws.send_text(
                json.dumps(
                    {
                        "type": "tts_start",
                        "utt_id": 0,
                        "format": "wav",
                        "bytes": len(audio),
                        "cached": cached,
                    }
                )
            )
            for i in range(0, len(audio), 16 * 1024):
                await self.ws.send_bytes(audio[i : i + 16 * 1024])
            await self.ws.send_text(json.dumps({"type": "tts_end", "utt_id": 0}))

    async def _release(self, reason: str) -> None:
        with contextlib.suppress(Exception):
            await self.svc.record_consent(self.inv_id, self.participant_id, False, reason)

    async def _fail(self, exc: ApiError) -> None:
        with contextlib.suppress(Exception):
            await self.send(
                {
                    "type": "error",
                    "code": exc.code,
                    "message": exc.message,
                    "status": exc.status,
                    "fatal": True,
                }
            )
        raise MediaClosedError(close_code_for(exc.status))

    async def _receive(self, kind: str, wait_s: float) -> dict[str, Any]:
        try:
            raw = await asyncio.wait_for(self.ws.receive_text(), wait_s)
            msg = json.loads(raw)
        except (TimeoutError, json.JSONDecodeError):
            msg = None
        if not isinstance(msg, dict) or msg.get("type") != kind:
            await self._fail(ApiError(400, "CALL_EXPECTED_" + kind.upper(), f"expected {kind}"))
        assert isinstance(msg, dict)
        return msg

    async def _receive_ring(self) -> str:
        """``accept``, ``decline`` or ``timeout`` (no answer within the ring time)."""
        try:
            raw = await asyncio.wait_for(self.ws.receive_text(), float(CALL_TIMERS.ring_s))
            msg = json.loads(raw)
        except TimeoutError:
            return "timeout"
        except json.JSONDecodeError:
            return "decline"
        kind = msg.get("type") if isinstance(msg, dict) else None
        return kind if kind in ("accept", "decline") else "decline"
