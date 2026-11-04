"""Call runtime state machine: every legal and illegal transition, timers and preemption."""

from __future__ import annotations

import itertools

import pytest

from pramana_core.calls import (
    TRANSITIONS,
    CallEvent,
    CallSession,
    CallState,
    CallTimers,
    IllegalTransitionError,
    Transition,
)

S, E = CallState, CallEvent

# PLAN.md section 12, edge by edge, plus "later" while talking and dropped connections.
EXPECTED = {
    (S.RINGING, E.ACCEPTED): S.CONSENT,
    (S.RINGING, E.DECLINED): S.UNAVAILABLE,
    (S.RINGING, E.RING_TIMEOUT): S.UNAVAILABLE,
    (S.CONSENT, E.CONSENT_YES): S.ASKING,
    (S.CONSENT, E.CONSENT_NO): S.CLOSING,
    (S.CONSENT, E.LATER): S.CLOSING,
    (S.ASKING, E.TTS_DONE): S.LISTENING,
    (S.ASKING, E.BARGE_IN): S.LISTENING,
    (S.ASKING, E.PREEMPT): S.PREEMPTING,
    (S.ASKING, E.LATER): S.CLOSING,
    (S.PREEMPTING, E.NEW_QUESTION): S.ASKING,
    (S.PREEMPTING, E.NO_QUESTION): S.CLOSING,
    (S.LISTENING, E.FINAL_TRANSCRIPT): S.EXTRACTING,
    (S.LISTENING, E.SILENCE_REPROMPT): S.ASKING,
    (S.LISTENING, E.SILENCE_TIMEOUT): S.UNAVAILABLE,
    (S.LISTENING, E.LATER): S.CLOSING,
    (S.EXTRACTING, E.INCOMPLETE): S.LISTENING,
    (S.EXTRACTING, E.NEEDS_CONFIRM): S.CONFIRMING,
    (S.EXTRACTING, E.OBSERVATION_PROPOSED): S.IDLE,
    (S.CONFIRMING, E.CONFIRM_ASKED): S.LISTENING,
    (S.IDLE, E.ASK): S.ASKING,
    (S.IDLE, E.CLOSE): S.CLOSING,
    (S.CLOSING, E.CLOSED): S.ENDED,
    (S.UNAVAILABLE, E.CLOSED): S.ENDED,
    **{
        (st, E.DISCONNECTED): S.UNAVAILABLE
        for st in (
            S.RINGING,
            S.CONSENT,
            S.ASKING,
            S.LISTENING,
            S.EXTRACTING,
            S.CONFIRMING,
            S.IDLE,
            S.PREEMPTING,
        )
    },
}


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, s: float) -> None:
        self.t += s


def session_in(state: CallState, clock: Clock | None = None) -> CallSession:
    s = CallSession("c1", "p_riya", clock=clock or Clock())
    s.state = state
    return s


def test_table_is_exactly_the_plan() -> None:
    assert TRANSITIONS == EXPECTED


@pytest.mark.parametrize(("state", "event"), list(itertools.product(CallState, CallEvent)))
def test_every_state_event_pair(state: CallState, event: CallEvent) -> None:
    s = session_in(state)
    if (state, event) in EXPECTED:
        t = s.fire(event)
        assert s.state == EXPECTED[(state, event)]
        assert (t.source, t.event, t.target) == (state, event, s.state)
    else:
        with pytest.raises(IllegalTransitionError):
            s.fire(event)
        assert s.state == state  # unchanged
        assert not s.history


def test_ended_is_terminal_and_reachable_from_everywhere() -> None:
    assert not [k for k in TRANSITIONS if k[0] == S.ENDED]
    # Every state can reach ENDED.
    reach = {S.ENDED}
    changed = True
    while changed:
        changed = False
        for (src, _), dst in TRANSITIONS.items():
            if dst in reach and src not in reach:
                reach.add(src)
                changed = True
    assert reach == set(CallState)


def test_happy_path_call() -> None:
    s = CallSession("c1", "p_mahesh", clock=Clock())
    seen: list[Transition] = []
    s.on_transition(seen.append)
    for ev in (
        E.ACCEPTED,
        E.CONSENT_YES,
        E.TTS_DONE,
        E.FINAL_TRANSCRIPT,
        E.OBSERVATION_PROPOSED,
        E.CLOSE,
        E.CLOSED,
    ):
        s.fire(ev)
    assert s.ended
    assert [t.target for t in seen][-1] == S.ENDED
    assert len(s.history) == 7


def test_ring_timeout_after_30_seconds() -> None:
    clock = Clock()
    s = CallSession("c1", "p", clock=clock)
    clock.advance(29.9)
    assert s.tick() is None
    assert s.next_deadline() == pytest.approx(1030.0)
    clock.advance(0.1)
    t = s.tick()
    assert t is not None
    assert t.event == E.RING_TIMEOUT
    assert s.state == S.UNAVAILABLE


def _listening(clock: Clock) -> CallSession:
    s = CallSession("c1", "p", clock=clock)
    s.fire(E.ACCEPTED)
    s.fire(E.CONSENT_YES)
    s.start_question("q1")
    s.fire(E.TTS_DONE)
    return s


def test_silence_reprompts_once_then_marks_unavailable() -> None:
    clock = Clock()
    s = _listening(clock)
    clock.advance(7.9)
    assert s.tick() is None
    clock.advance(0.1)
    t = s.tick()
    assert t is not None
    assert (t.event, s.state) == (E.SILENCE_REPROMPT, S.ASKING)
    clock.advance(5)  # the re-prompt is spoken: not silence
    s.fire(E.TTS_DONE)
    assert s.silence_s == pytest.approx(8.0)
    clock.advance(11.9)
    assert s.tick() is None  # no second re-prompt
    assert s.next_deadline() == pytest.approx(clock.t + 0.1)
    clock.advance(0.1)
    t = s.tick()
    assert t is not None
    assert (t.event, s.state) == (E.SILENCE_TIMEOUT, S.UNAVAILABLE)


def test_speech_resets_the_silence_clock() -> None:
    clock = Clock()
    s = _listening(clock)
    clock.advance(7)
    s.heard_speech()
    clock.advance(7)
    assert s.tick() is None
    clock.advance(1)
    t = s.tick()
    assert t is not None
    assert t.event == E.SILENCE_REPROMPT


def test_a_new_question_gets_its_own_reprompt() -> None:
    clock = Clock()
    s = _listening(clock)
    clock.advance(8)
    s.tick()
    s.fire(E.TTS_DONE)
    s.fire(E.FINAL_TRANSCRIPT)
    s.fire(E.OBSERVATION_PROPOSED)
    s.start_question("q2")
    s.fire(E.ASK)
    s.fire(E.TTS_DONE)
    assert s.silence_s == 0
    clock.advance(8)
    t = s.tick()
    assert t is not None
    assert t.event == E.SILENCE_REPROMPT


def test_preemption_hook_and_stale_utterances() -> None:
    clock = Clock()
    s = CallSession("c1", "p", clock=clock)
    assert s.preempt() is False  # nothing is being asked
    s.fire(E.ACCEPTED)
    s.fire(E.CONSENT_YES)
    first = s.utterance
    assert s.preempt() is True
    assert s.state == S.PREEMPTING
    s.fire(E.NEW_QUESTION)
    assert s.utterance == first + 1
    assert not s.is_current_utterance(first)
    assert s.is_current_utterance(s.utterance)
    s.fire(E.BARGE_IN)
    assert s.state == S.LISTENING
    assert s.preempt() is False  # once listening, the question stands


def test_confirmation_loop() -> None:
    s = session_in(S.EXTRACTING)
    s.fire(E.NEEDS_CONFIRM)
    s.fire(E.CONFIRM_ASKED)
    s.fire(E.FINAL_TRANSCRIPT)
    s.fire(E.INCOMPLETE)
    assert s.state == S.LISTENING


def test_timer_settings_are_validated() -> None:
    with pytest.raises(ValueError, match="reprompt"):
        CallTimers(reprompt_s=20, unavailable_s=8)
