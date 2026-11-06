"""Call runtime skeleton: an explicit, table-driven state machine for one participant's call.

The states and transitions are PLAN.md section 12. The machine is pure: it performs no I/O and
reads time only through an injected clock, so every transition and timer is testable without
sleeping. The gateway (audio) and the investigation runtime (questions, answers) drive it with
events and react to the transitions it reports.

Timers, all measured with the injected clock:

* ``RINGING`` for ``ring_s`` (30 s) without an answer -> ``UNAVAILABLE``.
* Silence while ``LISTENING`` accumulates per question. After ``reprompt_s`` (8 s) the question
  is re-asked once (``LISTENING -> ASKING``); after ``unavailable_s`` (20 s) in total the
  participant is treated as unavailable. Hearing speech resets the silence clock.

Preemption hooks: ``preempt()`` asks to abandon the current question, while it is being
spoken (``ASKING``) or while the answer is awaited (``LISTENING``, when it was answered elsewhere
or withdrawn). Each time the agent starts speaking, the utterance id increases, so audio and
transcripts belonging to an older utterance can be recognised and dropped
(``is_current_utterance``), following Retell's stale ``response_id`` rule.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum


class CallState(StrEnum):
    RINGING = "RINGING"
    CONSENT = "CONSENT"
    ASKING = "ASKING"
    LISTENING = "LISTENING"
    EXTRACTING = "EXTRACTING"
    CONFIRMING = "CONFIRMING"
    IDLE = "IDLE"
    PREEMPTING = "PREEMPTING"
    CLOSING = "CLOSING"
    UNAVAILABLE = "UNAVAILABLE"
    ENDED = "ENDED"


class CallEvent(StrEnum):
    ACCEPTED = "accepted"
    DECLINED = "declined"
    RING_TIMEOUT = "ring_timeout"
    CONSENT_YES = "consent_yes"
    CONSENT_NO = "consent_no"
    LATER = "later"
    TTS_DONE = "tts_done"
    BARGE_IN = "barge_in"
    PREEMPT = "preempt"
    NEW_QUESTION = "new_question"
    NO_QUESTION = "no_question"
    FINAL_TRANSCRIPT = "final_transcript"
    SILENCE_REPROMPT = "silence_reprompt"
    SILENCE_TIMEOUT = "silence_timeout"
    INCOMPLETE = "incomplete"
    NEEDS_CONFIRM = "needs_confirm"
    OBSERVATION_PROPOSED = "observation_proposed"
    CONFIRM_ASKED = "confirm_asked"
    ASK = "ask"
    CLOSE = "close"
    CLOSED = "closed"
    DISCONNECTED = "disconnected"


S, E = CallState, CallEvent

_ACTIVE = (S.CONSENT, S.ASKING, S.LISTENING, S.EXTRACTING, S.CONFIRMING, S.IDLE, S.PREEMPTING)

TRANSITIONS: dict[tuple[CallState, CallEvent], CallState] = {
    (S.RINGING, E.ACCEPTED): S.CONSENT,
    (S.RINGING, E.DECLINED): S.UNAVAILABLE,
    (S.RINGING, E.RING_TIMEOUT): S.UNAVAILABLE,
    (S.RINGING, E.DISCONNECTED): S.UNAVAILABLE,
    (S.CONSENT, E.CONSENT_YES): S.ASKING,
    (S.CONSENT, E.CONSENT_NO): S.CLOSING,
    (S.CONSENT, E.LATER): S.CLOSING,
    (S.ASKING, E.TTS_DONE): S.LISTENING,
    (S.ASKING, E.BARGE_IN): S.LISTENING,
    (S.ASKING, E.PREEMPT): S.PREEMPTING,
    (S.ASKING, E.LATER): S.CLOSING,
    (S.PREEMPTING, E.NEW_QUESTION): S.ASKING,
    (S.PREEMPTING, E.NO_QUESTION): S.CLOSING,
    (S.PREEMPTING, E.LATER): S.CLOSING,
    (S.LISTENING, E.FINAL_TRANSCRIPT): S.EXTRACTING,
    (S.LISTENING, E.SILENCE_REPROMPT): S.ASKING,
    (S.LISTENING, E.SILENCE_TIMEOUT): S.UNAVAILABLE,
    (S.LISTENING, E.LATER): S.CLOSING,
    # Not in PLAN section 12: the question was answered elsewhere or withdrawn while we were
    # listening. The call drops it and moves to the next question or closes.
    (S.LISTENING, E.PREEMPT): S.PREEMPTING,
    (S.EXTRACTING, E.INCOMPLETE): S.LISTENING,
    (S.EXTRACTING, E.NEEDS_CONFIRM): S.CONFIRMING,
    (S.EXTRACTING, E.OBSERVATION_PROPOSED): S.IDLE,
    (S.CONFIRMING, E.CONFIRM_ASKED): S.LISTENING,
    (S.IDLE, E.ASK): S.ASKING,
    (S.IDLE, E.LATER): S.CLOSING,
    (S.IDLE, E.CLOSE): S.CLOSING,
    (S.CLOSING, E.CLOSED): S.ENDED,
    (S.UNAVAILABLE, E.CLOSED): S.ENDED,
    # A dropped connection makes the participant unavailable from any active state.
    **{(st, E.DISCONNECTED): S.UNAVAILABLE for st in _ACTIVE},
}
"""Every legal transition. Anything not listed raises ``IllegalTransitionError``."""

TERMINAL = frozenset({S.ENDED})


class IllegalTransitionError(RuntimeError):
    def __init__(self, state: CallState, event: CallEvent) -> None:
        super().__init__(f"{event.value} is not allowed in {state.value}")
        self.state, self.event = state, event


@dataclass(frozen=True)
class CallTimers:
    ring_s: float = 30.0
    reprompt_s: float = 8.0
    unavailable_s: float = 20.0
    reprompts_per_question: int = 1

    def __post_init__(self) -> None:
        if not 0 < self.reprompt_s < self.unavailable_s:
            raise ValueError("require 0 < reprompt_s < unavailable_s")


@dataclass(frozen=True)
class Transition:
    at: float
    source: CallState
    event: CallEvent
    target: CallState
    utterance: int


Listener = Callable[[Transition], None]


@dataclass
class CallSession:
    call_id: str
    participant_id: str
    timers: CallTimers = field(default_factory=CallTimers)
    clock: Callable[[], float] = time.monotonic
    state: CallState = CallState.RINGING
    utterance: int = 0
    """Id of the agent's current utterance; increases every time the agent starts speaking."""
    question_id: str | None = None
    history: list[Transition] = field(default_factory=list)
    _listeners: list[Listener] = field(default_factory=list)
    _entered_at: float = 0.0
    _silence_s: float = 0.0
    _listen_started: float | None = None
    _reprompts: int = 0

    def __post_init__(self) -> None:
        self._entered_at = self.clock()

    # -- core ------------------------------------------------------------------------------

    def can(self, event: CallEvent) -> bool:
        return (self.state, event) in TRANSITIONS

    def on_transition(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def fire(self, event: CallEvent) -> Transition:
        target = TRANSITIONS.get((self.state, event))
        if target is None:
            raise IllegalTransitionError(self.state, event)
        now = self.clock()
        source = self.state
        if source == S.LISTENING:
            self._pause_silence(now)
        self.state, self._entered_at = target, now
        if target == S.ASKING:
            self.utterance += 1
        if target == S.LISTENING:
            self._listen_started = now
        if event == E.SILENCE_REPROMPT:
            self._reprompts += 1
        t = Transition(now, source, event, target, self.utterance)
        self.history.append(t)
        for listener in list(self._listeners):
            listener(t)
        return t

    # -- questions, speech and preemption -------------------------------------------------------

    def start_question(self, question_id: str) -> None:
        """A new question is about to be asked: reset per-question silence accounting."""
        self.question_id = question_id
        self._silence_s, self._reprompts, self._listen_started = 0.0, 0, None
        if self.state == S.LISTENING:
            self._listen_started = self.clock()

    def heard_speech(self) -> None:
        """Speech (``speech_start``) resets the silence clock."""
        self._silence_s = 0.0
        if self.state == S.LISTENING:
            self._listen_started = self.clock()

    def preempt(self) -> bool:
        """Preemption hook: abandon the question being spoken. False if not possible now."""
        if not self.can(E.PREEMPT):
            return False
        self.fire(E.PREEMPT)
        return True

    def is_current_utterance(self, utterance: int) -> bool:
        return utterance == self.utterance

    @property
    def silence_s(self) -> float:
        extra = 0.0
        if self.state == S.LISTENING and self._listen_started is not None:
            extra = self.clock() - self._listen_started
        return self._silence_s + extra

    @property
    def ended(self) -> bool:
        return self.state in TERMINAL

    def _pause_silence(self, now: float) -> None:
        if self._listen_started is not None:
            self._silence_s += now - self._listen_started
            self._listen_started = None

    # -- timers ---------------------------------------------------------------------------

    def due(self) -> CallEvent | None:
        """The timer event that is due now, if any (does not fire it)."""
        t = self.timers
        if self.state == S.RINGING and self.clock() - self._entered_at >= t.ring_s:
            return E.RING_TIMEOUT
        if self.state == S.LISTENING:
            silent = self.silence_s
            if silent >= t.unavailable_s:
                return E.SILENCE_TIMEOUT
            if silent >= t.reprompt_s and self._reprompts < t.reprompts_per_question:
                return E.SILENCE_REPROMPT
        return None

    def next_deadline(self) -> float | None:
        """Clock time at which the next timer becomes due (for the scheduler's sleep)."""
        t = self.timers
        if self.state == S.RINGING:
            return self._entered_at + t.ring_s
        if self.state == S.LISTENING and self._listen_started is not None:
            limit = t.reprompt_s if self._reprompts < t.reprompts_per_question else t.unavailable_s
            return self._listen_started + max(0.0, limit - self._silence_s)
        return None

    def tick(self) -> Transition | None:
        """Fire the due timer event, if any."""
        event = self.due()
        return None if event is None else self.fire(event)
