"""What a participant's join link may see of an investigation.

Staff see everything. A participant sees only what they need to take part: their own entry,
their own answers, a question addressed to them, approvals naming them, and the status. They
never see other people's answers, the engine's hypotheses or its plan: that would leak other
participants' words, and showing a witness the leading hypothesis invites them to confirm it.
The response keeps the ``InvestigationState`` shape, with those parts emptied.
"""

from __future__ import annotations

from pramana_contracts import (
    AnswerResult,
    BeliefSnapshot,
    ChallengeAnswerResult,
    InvestigationState,
    PlanDecision,
    VoiceAnswerResult,
)

from .auth.service import Principal

_HIDDEN_BELIEF = BeliefSnapshot(
    hypotheses=[],
    decisions=[],
    hypothesis_entropy_bits=0.0,
    decision_entropy_bits=0.0,
    open_world_probability=0.0,
    map_decision=None,
    map_decision_probability=0.0,
    expected_loss_now_min=0.0,
    observations_used=0,
)


def for_participant(state: InvestigationState, participant_id: str) -> InvestigationState:
    waiting = state.pending_questions or (
        [state.pending_question] if state.pending_question is not None else []
    )
    mine = [q for q in waiting if q.action.participant_id == participant_id]
    plan = state.plan
    hidden_plan = PlanDecision(
        kind=plan.kind,
        action=plan.action
        if plan.action is not None and plan.action.participant_id == participant_id
        else None,
        reason="",
        rule=plan.rule,
        candidates=[],
        infeasible=[],
    )
    return state.model_copy(
        update={
            "participants": [p for p in state.participants if p.id == participant_id],
            "belief": _HIDDEN_BELIEF,
            "plan": hidden_plan,
            "pending_question": mine[0] if mine else None,
            "pending_questions": mine,
            "observations": [o for o in state.observations if o.participant_id == participant_id],
            "approvals": [a for a in state.approvals if a.participant_id == participant_id],
            "ground_truth": None,
        }
    )


def visible_state(state: InvestigationState, who: Principal) -> InvestigationState:
    if who.kind != "participant" or who.participant_id is None:
        return state
    return for_participant(state, who.participant_id)


def visible_answer(
    result: AnswerResult | ChallengeAnswerResult, who: Principal
) -> AnswerResult | ChallengeAnswerResult:
    return result.model_copy(update={"state": visible_state(result.state, who)})


def visible_voice_answer(result: VoiceAnswerResult, who: Principal) -> VoiceAnswerResult:
    return result.model_copy(update={"result": visible_answer(result.result, who)})
