"""Investigation runtime: the only code path that mutates an investigation.

Consistency model:

* One writer per investigation. Commands for the same investigation are serialised by an
  in-process ``asyncio.Lock`` and, across processes, by ``SELECT ... FOR UPDATE`` on its row.
* Events are the source of truth. The engine is rebuilt by replaying ``QuestionAsked``,
  ``ObservationRecorded`` and ``ParticipantUnavailable`` in sequence order; replay is exact
  because the engine is deterministic.
* The in-memory engine is a cache keyed by the row's ``version``. A command mutates the cached
  engine before committing, so any failure evicts it; the next command rebuilds from events.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pramana_contracts import (
    ANSWERABLE_STATUSES,
    TERMINAL_STATUSES,
    UNKNOWN_OUTCOME,
    AnswerResult,
    Approval,
    ApprovalDecision,
    ApprovalStatus,
    CandidateScore,
    CapabilityGrant,
    ChallengeAnswerResult,
    ChallengeIssuedPayload,
    ChallengeResultPayload,
    ContradictionExplainedPayload,
    ContradictionResolvedPayload,
    CreateInvestigation,
    CreateScenario,
    Directness,
    EventEnvelope,
    Extraction,
    GroundTruthComparison,
    Hedge,
    InvestigationState,
    InvestigationStatus,
    Modality,
    Observation,
    ObservationState,
    ParticipantSpec,
    PlanDecision,
    PlanKind,
    ProbeAction,
    Question,
    QuestionStatus,
    Report,
    ReportIntervention,
    RequestApproval,
    SimParticipant,
    SubmitAnswer,
    TemplateLanguage,
)
from pramana_contracts.tokens import (
    ParticipantClaims,
    mint,
    mint_capability,
    private_key_from_b64,
)
from pramana_contracts.tokens import verify as verify_token
from pramana_domain import NO_FAULT, DomainPack, load_pack
from pramana_engine import (
    MODEL_VERSION,
    MULTIPLE_FAULTS,
    CompiledModel,
    Engine,
    EngineConfig,
    Evidence,
    EvidenceError,
    ObserveResult,
    compile_pack,
    schedule,
)

from .db import (
    ApprovalRow,
    Database,
    EventRow,
    InvestigationRow,
    ObservationRow,
    QuestionRow,
)
from .errors import ApiError, not_found
from .language.extraction import Extractor
from .language.intake import INTAKE_PROBE, parse_report
from .language.presence import normalize_presence_answer
from .language.realize import CONFIRM_PREFIX, realize
from .observability import log
from .sim_client import SimClient


@dataclass(frozen=True)
class StoredRequest:
    """The parts of a creation request the core keeps. The requested fault is never stored."""

    participants: list[ParticipantSpec]
    report: Report


@dataclass(frozen=True)
class PendingQuestion:
    id: str
    text: str
    language: TemplateLanguage
    probe_id: str
    participant: ParticipantSpec
    pack: DomainPack
    scenario_id: str = ""
    kind: str = "probe"
    presence_token_id: str | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def _not_pending(status: str) -> str:
    return {
        QuestionStatus.WITHDRAWN.value: "question was withdrawn: another answer made it pointless",
        QuestionStatus.CANCELLED.value: "question was cancelled",
    }.get(status, "question already answered")


def _opposed_observations(pack: DomainPack, first: Evidence, second: Evidence) -> bool:
    if first.probe_id == second.probe_id:
        return first.outcome != second.outcome
    signals: dict[str, dict[str, bool]] = {
        "internet_works": {"yes": True, "no": False},
        "web_by_ip": {"yes": True, "no": False},
        "wifi_status": {
            "connected": True,
            "no_network": False,
            "stuck_connecting": False,
        },
        "wifi_access_point": {"AP_2A": True, "AP_2B": True, "not_connected": False},
    }
    first_kind = pack.probe_by_id[first.probe_id].kind
    second_kind = pack.probe_by_id[second.probe_id].kind
    first_signal = signals.get(first_kind, {}).get(first.outcome)
    second_signal = signals.get(second_kind, {}).get(second.outcome)
    return first_signal is not None and second_signal is not None and first_signal != second_signal


_CHALLENGE_FAILURE: dict[TemplateLanguage, str] = {
    "en": "I couldn't confirm the location; I'll ask someone else.",
    "hi": "मैं जगह की पुष्टि नहीं कर पाया; मैं किसी और से पूछूँगा।",
    "mr": "मी जागेची खात्री करू शकलो नाही; मी दुसऱ्या व्यक्तीला विचारेन.",
    "hi-en": "Location confirm nahi ho saki; main kisi aur se poochunga.",
}
_CHALLENGE_SUCCESS: dict[TemplateLanguage, str] = {
    "en": "Location confirmed.",
    "hi": "जगह की पुष्टि हो गई।",
    "mr": "जागेची खात्री झाली.",
    "hi-en": "Location confirm ho gayi.",
}


class InvestigationService:
    def __init__(
        self,
        db: Database,
        sim: SimClient,
        extractor: Extractor,
        signing_key_b64: str,
        engine_config: EngineConfig | None = None,
        browser_sim_url: str = "http://127.0.0.1:8100",
    ) -> None:
        self.browser_sim_url = browser_sim_url
        self.db = db
        self.sim = sim
        self.extractor = extractor
        self._signing_key = private_key_from_b64(signing_key_b64)
        self._engine_config = engine_config or EngineConfig()
        self._models: dict[str, CompiledModel] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._cache: dict[str, tuple[int, Engine]] = {}

    # -- helpers ---------------------------------------------------------------------------------

    def model(self, pack_id: str) -> CompiledModel:
        if pack_id not in self._models:
            try:
                self._models[pack_id] = compile_pack(load_pack(pack_id))
            except (FileNotFoundError, ValueError) as exc:
                raise ApiError(422, "UNKNOWN_PACK", f"unknown pack {pack_id}") from exc
        return self._models[pack_id]

    def pack(self, pack_id: str) -> DomainPack:
        return self.model(pack_id).pack

    def _lock(self, inv_id: str) -> asyncio.Lock:
        return self._locks.setdefault(inv_id, asyncio.Lock())

    @staticmethod
    def _event(
        session: AsyncSession,
        inv_id: str,
        type_: str,
        payload: dict[str, Any],
        key: str | None = None,
    ) -> None:
        session.add(
            EventRow(investigation_id=inv_id, type=type_, payload=payload, idempotency_key=key)
        )

    @staticmethod
    def _request(row: InvestigationRow) -> StoredRequest:
        return StoredRequest(
            participants=[ParticipantSpec.model_validate(p) for p in row.request["participants"]],
            report=Report.model_validate(row.request["report"]),
        )

    async def _load_row(self, session: AsyncSession, inv_id: str, lock: bool) -> InvestigationRow:
        stmt = select(InvestigationRow).where(InvestigationRow.id == inv_id)
        if lock:
            stmt = stmt.with_for_update()
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise not_found("investigation")
        return row

    async def _engine(self, session: AsyncSession, row: InvestigationRow) -> Engine:
        cached = self._cache.get(row.id)
        if cached is not None and cached[0] == row.version:
            return cached[1]
        engine, _ = await self._rebuild(session, row)
        self._cache[row.id] = (row.version, engine)
        return engine

    async def _rebuild(self, session: AsyncSession, row: InvestigationRow) -> tuple[Engine, int]:
        """A fresh engine built only from the event log; also returns how many events it read."""
        req = self._request(row)
        engine = Engine(self.model(row.pack_id), list(req.participants), self._engine_config)
        events = await session.execute(
            select(EventRow.type, EventRow.payload)
            .where(EventRow.investigation_id == row.id)
            .order_by(EventRow.seq)
        )
        rows = events.all()
        for type_, payload in rows:
            if type_ == "QuestionAsked":
                action = payload["action"]
                engine.record_question(
                    action["participant_id"], action.get("probe_id"), action.get("location_id")
                )
            elif type_ == "ChallengeIssued":
                engine.record_presence_challenge(
                    payload["participant_id"], payload["location_id"], payload.get("probe_id")
                )
            elif type_ == "ChallengeResult":
                passed = payload["result"] == "passed"
                engine.set_presence(
                    payload["participant_id"],
                    payload["location_id"],
                    passed,
                    challenge_failed=payload["result"] == "failed",
                )
                if payload["result"] == "failed":
                    engine.set_available(payload["participant_id"], False)
            elif type_ == "ObservationRecorded":
                e = payload["evidence"]
                engine.observe(
                    Evidence(
                        e["participant_id"],
                        e["probe_id"],
                        e["location_id"],
                        e["outcome"],
                        Hedge(e["hedge"]),
                        Directness(e["directness"]),
                        Modality(e.get("modality", "text")),
                    )
                )
            elif type_ == "ParticipantUnavailable":
                engine.set_available(payload["participant_id"], False)
            elif type_ == "ObservationConfirmed" and payload.get("agreed") is not None:
                engine.confirm(
                    payload["participant_id"],
                    payload["probe_id"],
                    payload["location_id"],
                    bool(payload["agreed"]),
                )
            elif type_ == "Reopened":
                engine.reopen()
            elif type_ == "InterventionReported":
                engine.apply_intervention(
                    payload["action"], payload["target"], payload["participant_id"]
                )
        return engine, len(rows)

    def _record_observation(
        self,
        session: AsyncSession,
        inv_id: str,
        engine: Engine,
        ev: Evidence,
        extraction: Extraction,
        *,
        question_id: str | None,
        modality: str,
        transcript: str | None,
    ) -> tuple[Observation, ObserveResult]:
        try:
            result = engine.observe(ev)
        except EvidenceError as exc:
            raise ApiError(422, "INVALID_OBSERVATION", str(exc)) from exc
        obs = Observation(
            id=_id("obs"),
            question_id=question_id,
            participant_id=ev.participant_id,
            probe_id=ev.probe_id,
            location_id=ev.location_id,
            outcome=ev.outcome,
            hedge=ev.hedge,
            directness=ev.directness,
            modality=modality,
            transcript=transcript,
            extraction_method=extraction.method,
            injection_suspected=extraction.injection_suspected,
            state=ObservationState.COMMITTED
            if result.used_as_evidence
            else ObservationState.DISCARDED,
            committed_at=_now(),
        )
        session.add(ObservationRow(investigation_id=inv_id, **obs.model_dump()))
        self._event(
            session,
            inv_id,
            "ObservationRecorded",
            {
                "observation_id": obs.id,
                "evidence": {
                    "participant_id": ev.participant_id,
                    "probe_id": ev.probe_id,
                    "location_id": ev.location_id,
                    "outcome": ev.outcome,
                    "hedge": ev.hedge.value,
                    "directness": ev.directness.value,
                    "modality": ev.modality.value,
                },
                "used_as_evidence": result.used_as_evidence,
                "reason": result.reason,
                "superseded_previous": result.superseded,
                "contradiction": result.contradiction,
                "surprise_bits": result.surprise_bits,
                "extraction": extraction.model_dump(mode="json"),
                "decision_critical": result.decision_critical,
                "multiple_faults_suspected": result.multiple_faults_suspected,
            },
        )
        if result.contradiction:
            self._event(
                session,
                inv_id,
                "ContradictionDetected",
                {
                    "observation_id": obs.id,
                    "participant_id": ev.participant_id,
                    "probe_id": ev.probe_id,
                    "location_id": ev.location_id,
                    "outcome": ev.outcome,
                    "conflicts_with": result.contradiction,
                },
            )
        return obs, result

    async def _explain_contradiction(
        self,
        session: AsyncSession,
        inv_id: str,
        engine: Engine,
        observation: Observation,
        current: Evidence,
    ) -> str | None:
        """Persist the ranked, language independent explanation for an opposing reading."""
        pack = engine.model.pack
        prior = next(
            (
                item
                for item in reversed(engine.evidence()[:-1])
                if _opposed_observations(pack, item, current)
            ),
            None,
        )
        if prior is None:
            return None
        prior_row = (
            await session.execute(
                select(ObservationRow)
                .where(
                    ObservationRow.investigation_id == inv_id,
                    ObservationRow.participant_id == prior.participant_id,
                    ObservationRow.probe_id == prior.probe_id,
                    ObservationRow.location_id == prior.location_id,
                    ObservationRow.outcome == prior.outcome,
                    ObservationRow.state == ObservationState.COMMITTED.value,
                )
                .order_by(ObservationRow.committed_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if prior_row is None:
            return None
        explanation = engine.explain_reconciliation(prior, current)
        explanation_id = observation.id
        payload = ContradictionExplainedPayload(
            explanation_id=explanation_id,
            observation_ids=(prior_row.id, observation.id),
            families=[
                {
                    "code": family.code,
                    "posterior_mass": family.posterior_mass,
                    "supported": family.supported,
                }
                for family in explanation.families
            ],
            contexts=[
                {
                    "participant_ids": context.participant_ids,
                    "location_ids": context.location_ids,
                    "access_points": context.access_points,
                    "posterior_mass": context.posterior_mass,
                }
                for context in explanation.contexts
            ],
            tie_break_action=explanation.tie_break_action,
        )
        self._event(session, inv_id, "ContradictionExplained", payload.model_dump(mode="json"))
        return explanation_id

    async def _pending_tie_break(
        self, session: AsyncSession, inv_id: str
    ) -> tuple[str, ProbeAction] | None:
        explanations = (
            await session.execute(
                select(EventRow.payload)
                .where(
                    EventRow.investigation_id == inv_id,
                    EventRow.type == "ContradictionExplained",
                )
                .order_by(EventRow.seq.desc())
            )
        ).scalars()
        asked = (
            await session.execute(
                select(EventRow.payload).where(
                    EventRow.investigation_id == inv_id,
                    EventRow.type == "QuestionAsked",
                )
            )
        ).scalars()
        answered_ids = {
            payload.get("tie_break_for") for payload in asked if payload.get("tie_break_for")
        }
        for payload in explanations:
            explanation_id = payload["explanation_id"]
            action = payload.get("tie_break_action")
            if action is not None and explanation_id not in answered_ids:
                return explanation_id, ProbeAction.model_validate(action)
        return None

    async def _tie_break_id(
        self, session: AsyncSession, inv_id: str, question_id: str
    ) -> str | None:
        payloads = (
            await session.execute(
                select(EventRow.payload).where(
                    EventRow.investigation_id == inv_id,
                    EventRow.type == "QuestionAsked",
                )
            )
        ).scalars()
        return next(
            (
                str(payload["tie_break_for"])
                for payload in payloads
                if payload.get("question_id") == question_id and payload.get("tie_break_for")
            ),
            None,
        )

    async def _supersede(self, session: AsyncSession, inv_id: str, obs: Observation) -> None:
        """Mark earlier committed answers by the same person to the same site as superseded."""
        rows = await session.execute(
            select(ObservationRow).where(
                ObservationRow.investigation_id == inv_id,
                ObservationRow.participant_id == obs.participant_id,
                ObservationRow.probe_id == obs.probe_id,
                ObservationRow.location_id == obs.location_id,
                ObservationRow.state == ObservationState.COMMITTED.value,
                ObservationRow.id != obs.id,
            )
        )
        for old in rows.scalars():
            old.state = ObservationState.SUPERSEDED.value

    def _ask(
        self,
        session: AsyncSession,
        row: InvestigationRow,
        engine: Engine,
        action: ProbeAction,
        parallel: CandidateScore | None = None,
        tie_break_for: str | None = None,
    ) -> None:
        """Address one question to one person and log it."""
        req = self._request(row)
        person = next(p for p in req.participants if p.id == action.participant_id)
        lang = person.languages.template_language
        text = realize(self.pack(row.pack_id), action, lang)
        qid = _id("q")
        session.add(
            QuestionRow(
                id=qid,
                investigation_id=row.id,
                participant_id=action.participant_id,
                probe_id=action.probe_id,
                location_id=action.location_id,
                requires_move=action.requires_move,
                language=lang,
                text=text,
                status=QuestionStatus.PENDING.value,
                asked_at=_now(),
            )
        )
        engine.record_question(action.participant_id, action.probe_id, action.location_id)
        payload: dict[str, Any] = {
            "question_id": qid,
            "action": action.model_dump(mode="json"),
            "language": lang,
            "text": text,
        }
        if parallel is not None:
            payload["parallel"] = {
                "conditional_decision_bits": parallel.eig_decision_bits,
                "conditional_hypothesis_bits": parallel.eig_hypothesis_bits,
                "cost_s": parallel.cost_s,
                "net_value_min": parallel.net_value_min,
            }
        if tie_break_for is not None:
            payload["tie_break_for"] = tie_break_for
        self._event(session, row.id, "QuestionAsked", payload)

    def _issue_presence_challenge(
        self,
        session: AsyncSession,
        row: InvestigationRow,
        engine: Engine,
        *,
        participant_id: str,
        probe_id: str,
        location_id: str,
    ) -> str | None:
        """Reserve and ask the one label question for this participant and location."""
        pack = self.pack(row.pack_id)
        token = next(
            (item for item in pack.presence_tokens if item.location_id == location_id), None
        )
        if token is None or not engine.record_presence_challenge(
            participant_id, location_id, probe_id
        ):
            return None
        req = self._request(row)
        person = next(p for p in req.participants if p.id == participant_id)
        language = person.languages.template_language
        place = pack.location_by_id[location_id].label.get(language)
        text = token.prompt_templates[language].format(length=token.length, place=place)
        qid = _id("q")
        action = ProbeAction(
            participant_id=participant_id,
            probe_id=probe_id,
            location_id=location_id,
            requires_move=True,
        )
        session.add(
            QuestionRow(
                id=qid,
                investigation_id=row.id,
                participant_id=participant_id,
                probe_id=probe_id,
                location_id=location_id,
                requires_move=action.requires_move,
                language=language,
                text=text,
                status=QuestionStatus.PENDING.value,
                kind="challenge",
                presence_token_id=token.id,
                asked_at=_now(),
            )
        )
        engine.record_question(participant_id, probe_id, location_id)
        challenge = ChallengeIssuedPayload(
            challenge_id=qid,
            question_id=qid,
            participant_id=participant_id,
            probe_id=probe_id,
            location_id=location_id,
            token_id=token.id,
            cost_s=engine.cfg.presence_challenge_cost_s,
        )
        self._event(session, row.id, "ChallengeIssued", challenge.model_dump(mode="json"))
        self._event(
            session,
            row.id,
            "QuestionAsked",
            {
                "question_id": qid,
                "action": action.model_dump(mode="json"),
                "language": language,
                "text": text,
                "kind": "challenge",
                "presence_token_id": token.id,
            },
        )
        return qid

    async def _schedule(self, session: AsyncSession, row: InvestigationRow, engine: Engine) -> None:
        """After any change of belief: withdraw questions that stopped mattering, then ask or
        conclude (``pramana_engine.schedule``, docs/adr/0011). With one call at a time this is
        exactly the sequential planner."""
        limit = int(row.request.get("max_parallel_calls", 1))
        pending = list(
            (
                await session.execute(
                    select(QuestionRow)
                    .where(
                        QuestionRow.investigation_id == row.id,
                        QuestionRow.status == QuestionStatus.PENDING.value,
                    )
                    .order_by(QuestionRow.asked_at, QuestionRow.id)
                )
            )
            .scalars()
            .all()
        )
        pending_tie_break = await self._pending_tie_break(session, row.id)
        if pending_tie_break is not None and not pending:
            explanation_id, action = pending_tie_break
            baseline = engine.plan()
            forced = baseline.model_copy(
                update={
                    "kind": PlanKind.ASK,
                    "action": action,
                    "decision_class": None,
                    "decision_probability": None,
                    "moderate_confidence": False,
                    "reason": "A location-specific check can separate the conflicting reports.",
                    "rule": "positive_value",
                }
            )
            self._apply_plan(session, row, engine, forced, tie_break_for=explanation_id)
            return
        challenge_questions = [q for q in pending if q.kind == "challenge"]
        planner_questions = [q for q in pending if q.kind != "challenge"]
        actions = [
            ProbeAction(
                participant_id=q.participant_id,
                probe_id=q.probe_id,
                location_id=q.location_id,
                requires_move=q.requires_move,
            )
            for q in planner_questions
        ]
        remaining_slots = max(1, limit - len(challenge_questions))
        step = schedule(engine, actions, remaining_slots)
        if (
            len(challenge_questions) >= limit
            and step.plan is not None
            and step.plan.kind == PlanKind.ASK
        ):
            step = step.__class__(withdraw=step.withdraw, plan=None)
        if challenge_questions and step.plan is not None:
            plan = step.plan
            challenge_resolved_by_conclusion = (
                plan.kind in (PlanKind.VERIFIED, PlanKind.NOT_VERIFIED)
                or (plan.kind == PlanKind.DECIDE and plan.rule == "confident")
                or (plan.kind == PlanKind.ABSTAIN and plan.rule == "open_world")
            )
            if not challenge_resolved_by_conclusion and plan.kind != PlanKind.ASK:
                # An unresolved challenge can restore full-weight evidence. Moderate decisions
                # and low-confidence abstentions must wait for it rather than cancel it.
                step = step.__class__(withdraw=step.withdraw, plan=None)
        conclusive = step.plan is not None and step.plan.kind != PlanKind.ASK
        for i in step.withdraw:
            q = planner_questions[i]
            q.status = QuestionStatus.WITHDRAWN.value
            self._event(
                session,
                row.id,
                "QuestionWithdrawn",
                {
                    "question_id": q.id,
                    "participant_id": q.participant_id,
                    "reason": "the investigation reached a conclusion"
                    if conclusive
                    else "another answer made this question pointless",
                },
            )
        if conclusive:
            for q in challenge_questions:
                q.status = QuestionStatus.WITHDRAWN.value
                engine.set_presence(q.participant_id, q.location_id, False)
                self._event(
                    session,
                    row.id,
                    "QuestionWithdrawn",
                    {
                        "question_id": q.id,
                        "participant_id": q.participant_id,
                        "reason": "the investigation reached a conclusion",
                    },
                )
                self._event(
                    session,
                    row.id,
                    "ChallengeResult",
                    ChallengeResultPayload(
                        challenge_id=q.id,
                        participant_id=q.participant_id,
                        location_id=q.location_id,
                        result="withdrawn",
                        reason="decision_reached",
                    ).model_dump(mode="json"),
                )
        if step.plan is not None:
            self._apply_plan(session, row, engine, step.plan)
        else:
            self._event(session, row.id, "BeliefUpdated", engine.snapshot().model_dump(mode="json"))
        for extra in step.ask:
            self._ask(session, row, engine, extra.action, parallel=extra)

    def _apply_plan(
        self,
        session: AsyncSession,
        row: InvestigationRow,
        engine: Engine,
        plan: PlanDecision,
        *,
        tie_break_for: str | None = None,
    ) -> None:
        """Record the plan; ask the next question or conclude."""
        self._event(session, row.id, "BeliefUpdated", engine.snapshot().model_dump(mode="json"))
        self._event(session, row.id, "PlanComputed", plan.model_dump(mode="json"))
        if plan.kind == PlanKind.ASK:
            assert plan.action is not None
            self._ask(session, row, engine, plan.action, tie_break_for=tie_break_for)
            row.status = (
                InvestigationStatus.VERIFYING
                if engine.snapshot().repair is not None
                else InvestigationStatus.INVESTIGATING
            ).value
            return
        if plan.kind in (PlanKind.VERIFIED, PlanKind.NOT_VERIFIED):
            verified = plan.kind == PlanKind.VERIFIED
            row.status = (
                InvestigationStatus.VERIFIED if verified else InvestigationStatus.NOT_VERIFIED
            ).value
            verdict = {
                "kind": plan.kind.value,
                "rule": plan.rule,
                "fixed_probability": plan.decision_probability,
                "reason": plan.reason,
            }
            row.outcome = {**(row.outcome or {}), "verification": verdict}
            self._event(session, row.id, "VerificationResult", verdict)
            if plan.rule == "verification_failed":
                # The repair did not resolve it: reopen with the alternatives promoted.
                engine.reopen()
                self._event(session, row.id, "Reopened", {"reason": plan.reason})
                self._apply_plan(session, row, engine, engine.plan())
            return
        decided = plan.kind == PlanKind.DECIDE
        row.status = (
            InvestigationStatus.DECIDED if decided else InvestigationStatus.ABSTAINED
        ).value
        row.outcome = {
            "kind": plan.kind.value,
            "decision_class": plan.decision_class,
            "decision_probability": plan.decision_probability,
            "rule": plan.rule,
            "moderate_confidence": plan.moderate_confidence,
            "reason": plan.reason,
        }
        self._event(session, row.id, "DecisionReached" if decided else "Abstained", row.outcome)

    async def _second_decode_agrees(
        self,
        session: AsyncSession,
        inv_id: str,
        engine: Engine,
        q: QuestionRow,
        extraction: Extraction,
        outcomes: list[str],
        second_decode: Callable[[], Awaitable[str | None]] | None,
    ) -> bool:
        """Confirm a decision-critical spoken answer from a second, independent recognition of
        the same audio (no answer vocabulary or question as context, so it is not biased toward
        the expected words). Agreement removes the speech discount, as a re-asked answer would;
        anything else (disagreement, nothing heard, a failure) falls back to asking again."""
        if second_decode is None:
            return False
        try:
            alt = await second_decode()
        except Exception as exc:  # budget, rate limit, provider error: ask the person instead
            log.warning("second_decode_failed", investigation_id=inv_id, error=type(exc).__name__)
            return False
        if not alt:
            return False
        heard = await self.extractor.extract(alt, outcomes, question=q.text)
        if heard.outcome != extraction.outcome or heard.injection_suspected:
            log.info(
                "second_decode_disagrees",
                investigation_id=inv_id,
                first=extraction.outcome,
                second=heard.outcome,
            )
            return False
        engine.confirm(q.participant_id, q.probe_id, q.location_id, True)
        self._event(
            session,
            inv_id,
            "ObservationConfirmed",
            {
                "participant_id": q.participant_id,
                "probe_id": q.probe_id,
                "location_id": q.location_id,
                "original_outcome": extraction.outcome,
                "heard": heard.outcome,
                "agreed": True,
                "question_id": q.id,
                "method": "second_decode",
            },
        )
        return True

    def _ask_confirmation(
        self, session: AsyncSession, row: InvestigationRow, engine: Engine, asked: QuestionRow
    ) -> None:
        """Re-ask the same item-specific question (not "did you say X?"), same person."""
        lang = cast(TemplateLanguage, asked.language)
        qid = _id("q")
        text = CONFIRM_PREFIX[lang] + " " + asked.text
        session.add(
            QuestionRow(
                id=qid,
                investigation_id=row.id,
                participant_id=asked.participant_id,
                probe_id=asked.probe_id,
                location_id=asked.location_id,
                requires_move=False,
                language=asked.language,
                text=text,
                status=QuestionStatus.PENDING.value,
                kind="confirm",
                asked_at=_now(),
            )
        )
        engine.record_question(asked.participant_id)
        action = {
            "participant_id": asked.participant_id,
            "probe_id": asked.probe_id,
            "location_id": asked.location_id,
            "requires_move": False,
        }
        self._event(
            session,
            row.id,
            "QuestionAsked",
            {
                "question_id": qid,
                "action": action,
                "language": asked.language,
                "text": text,
                "kind": "confirm",
                "confirms_question": asked.id,
            },
        )

    async def _apply_confirmation(
        self,
        session: AsyncSession,
        inv_id: str,
        engine: Engine,
        q: QuestionRow,
        extraction: Extraction,
    ) -> Observation:
        """Agreement removes the speech discount; disagreement discards the earlier answer."""
        original = (
            await session.execute(
                select(ObservationRow)
                .where(
                    ObservationRow.investigation_id == inv_id,
                    ObservationRow.participant_id == q.participant_id,
                    ObservationRow.probe_id == q.probe_id,
                    ObservationRow.location_id == q.location_id,
                    ObservationRow.state == ObservationState.COMMITTED.value,
                )
                .order_by(ObservationRow.committed_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if original is None:
            raise ApiError(409, "NOTHING_TO_CONFIRM", "the answer being confirmed was not found")
        agreed: bool | None = None
        if extraction.outcome != UNKNOWN_OUTCOME:
            agreed = extraction.outcome == original.outcome
            engine.confirm(q.participant_id, q.probe_id, q.location_id, agreed)
            if not agreed:
                original.state = ObservationState.DISCARDED.value
        self._event(
            session,
            inv_id,
            "ObservationConfirmed",
            {
                "participant_id": q.participant_id,
                "probe_id": q.probe_id,
                "location_id": q.location_id,
                "original_outcome": original.outcome,
                "heard": extraction.outcome,
                "agreed": agreed,
                "question_id": q.id,
            },
        )
        return Observation.model_validate(
            {c: getattr(original, c) for c in Observation.model_fields}
        )

    # -- commands --------------------------------------------------------------------------------

    async def create(self, req: CreateInvestigation) -> InvestigationState:
        pack = self.pack(req.pack_id)
        for p in req.participants:
            if p.location_id not in pack.location_by_id:
                raise ApiError(
                    422, "UNKNOWN_LOCATION", f"participant {p.id}: unknown location {p.location_id}"
                )
        scenario = await self.sim.create_scenario(
            CreateScenario(
                pack_id=req.pack_id,
                seed=req.scenario.seed,
                fault=req.scenario.fault,
                participants=[
                    SimParticipant(
                        id=p.id, location_id=p.location_id, roles=[r.value for r in p.roles]
                    )
                    for p in req.participants
                ],
            )
        )
        inv_id = _id("inv")
        # The requested fault (if any) is NOT stored by the core: only the simulator keeps it.
        stored = req.model_dump(mode="json")
        stored["scenario"] = {"seed": req.scenario.seed, "fault": "sealed"}
        row = InvestigationRow(
            id=inv_id,
            pack_id=req.pack_id,
            status=InvestigationStatus.INVESTIGATING.value,
            scenario_id=scenario.scenario_id,
            commitment=scenario.commitment,
            request=stored,
            version=0,
        )
        engine = Engine(self.model(req.pack_id), list(req.participants), self._engine_config)
        async with self._lock(inv_id), self.db.transaction() as session:
            session.add(row)
            await session.flush()
            self._event(
                session,
                inv_id,
                "InvestigationCreated",
                {
                    "pack_id": req.pack_id,
                    "scenario_id": scenario.scenario_id,
                    "commitment": scenario.commitment,
                    "participants": stored["participants"],
                    "engine_model_version": MODEL_VERSION,
                },
            )
            self._event(session, inv_id, "ReportReceived", req.report.model_dump(mode="json"))
            await self._intake(session, row, engine, req)
            await self._schedule(session, row, engine)
            row.version = 1
        self._cache[inv_id] = (row.version, engine)
        log.info("investigation_created", investigation_id=inv_id, status=row.status)
        return await self.get(inv_id)

    async def _intake(
        self, session: AsyncSession, row: InvestigationRow, engine: Engine, req: CreateInvestigation
    ) -> None:
        """Map the report to evidence only when it explicitly answers the intake probe."""
        reporter = next(p for p in req.participants if p.id == req.report.reporter_id)
        parsed = await parse_report(
            req.report.text, self.pack(req.pack_id), reporter.location_id, self.extractor
        )
        # Hints (floors, rooms, symptoms) are shown, never used as evidence.
        self._event(session, row.id, "IntakeParsed", parsed.hints())
        extraction = parsed.extraction
        if extraction is None:
            return
        if extraction.outcome == UNKNOWN_OUTCOME:
            self._event(session, row.id, "IntakeUnmapped", extraction.model_dump(mode="json"))
            return
        ev = Evidence(
            reporter.id,
            INTAKE_PROBE,
            reporter.location_id,
            extraction.outcome,
            extraction.hedge,
            extraction.directness,
        )
        _ = self._record_observation(
            session,
            row.id,
            engine,
            ev,
            extraction,
            question_id=None,
            modality="text",
            transcript=req.report.text,
        )

    async def answer(
        self,
        inv_id: str,
        ans: SubmitAnswer,
        *,
        second_decode: Callable[[], Awaitable[str | None]] | None = None,
    ) -> AnswerResult | ChallengeAnswerResult:
        """Record an answer. ``second_decode`` (spoken answers only) returns an independent
        transcript of the same audio; it is called only if the decision hinges on this answer.
        If it reads the same outcome, the answer counts as confirmed without asking again."""
        challenge_reply: tuple[bool, str] | None = None
        async with self._lock(inv_id):
            try:
                async with self.db.transaction() as session:
                    row = await self._load_row(session, inv_id, lock=True)
                    if row.status not in {st.value for st in ANSWERABLE_STATUSES}:
                        raise ApiError(
                            409, "INVESTIGATION_NOT_ACTIVE", f"investigation is {row.status}"
                        )
                    q = await session.get(QuestionRow, ans.question_id, with_for_update=True)
                    if q is None or q.investigation_id != inv_id:
                        raise not_found("question")
                    if q.status != QuestionStatus.PENDING.value:
                        raise ApiError(409, "QUESTION_NOT_PENDING", _not_pending(q.status))
                    if q.participant_id != ans.participant_id:
                        raise ApiError(
                            403,
                            "WRONG_PARTICIPANT",
                            "question was addressed to another participant",
                        )
                    engine = await self._engine(session, row)
                    tie_break_id = await self._tie_break_id(session, inv_id, q.id)
                    if q.kind == "challenge":
                        if q.presence_token_id is None:
                            raise ApiError(409, "CHALLENGE_TOKEN_MISSING", "presence token missing")
                        token = self.pack(row.pack_id).presence_token_by_id[q.presence_token_id]
                        raw_answer = ans.text if ans.text is not None else (ans.outcome or "")
                        normalized = normalize_presence_answer(raw_answer, token.length)
                        checked = await self.sim.verify_presence(
                            row.scenario_id,
                            q.participant_id,
                            q.presence_token_id,
                            normalized or "",
                        )
                        passed = checked.passed
                        engine.set_presence(
                            q.participant_id,
                            q.location_id,
                            passed,
                            challenge_failed=not passed,
                        )
                        if not passed:
                            engine.set_available(q.participant_id, False)
                        q.status, q.answered_at = QuestionStatus.ANSWERED.value, _now()
                        self._event(
                            session,
                            inv_id,
                            "ChallengeResult",
                            ChallengeResultPayload(
                                challenge_id=q.id,
                                participant_id=q.participant_id,
                                location_id=q.location_id,
                                result="passed" if passed else "failed",
                                reason="label_matched" if passed else "label_unavailable",
                            ).model_dump(mode="json"),
                        )
                        await self._schedule(session, row, engine)
                        row.version += 1
                        version = row.version
                        language = cast(TemplateLanguage, q.language)
                        challenge_reply = (
                            passed,
                            _CHALLENGE_SUCCESS[language]
                            if passed
                            else _CHALLENGE_FAILURE[language],
                        )
                    else:
                        outcomes = list(self.model(row.pack_id).outcomes[q.probe_id])
                        if ans.text is not None:
                            extraction = await self.extractor.extract(
                                ans.text, outcomes, question=q.text
                            )
                        else:
                            if ans.outcome not in (*outcomes, UNKNOWN_OUTCOME):
                                raise ApiError(
                                    422, "INVALID_OUTCOME", f"outcome must be one of {outcomes}"
                                )
                            extraction = Extraction(
                                outcome=ans.outcome or UNKNOWN_OUTCOME,
                                hedge=ans.hedge,
                                directness=ans.directness,
                                method="structured",
                            )
                        ev = Evidence(
                            q.participant_id,
                            q.probe_id,
                            q.location_id,
                            extraction.outcome,
                            extraction.hedge,
                            extraction.directness,
                            ans.modality,
                        )
                        q.status, q.answered_at = QuestionStatus.ANSWERED.value, _now()
                        if q.kind == "confirm":
                            obs = await self._apply_confirmation(
                                session, inv_id, engine, q, extraction
                            )
                            await self._schedule(session, row, engine)
                            row.version += 1
                            version = row.version
                            continue_planning = False
                        else:
                            obs, observed = self._record_observation(
                                session,
                                row.id,
                                engine,
                                ev,
                                extraction,
                                question_id=q.id,
                                modality=ans.modality.value,
                                transcript=ans.text,
                            )
                            await self._supersede(session, inv_id, obs)
                            if tie_break_id is not None and extraction.outcome != UNKNOWN_OUTCOME:
                                self._event(
                                    session,
                                    inv_id,
                                    "ContradictionResolved",
                                    ContradictionResolvedPayload(
                                        explanation_id=tie_break_id,
                                        question_id=q.id,
                                        outcome=extraction.outcome,
                                    ).model_dump(mode="json"),
                                )
                            await self._explain_contradiction(session, inv_id, engine, obs, ev)
                            continue_planning = True
                            critical = (
                                ans.modality == Modality.VOICE
                                and observed.used_as_evidence
                                and observed.decision_critical
                            )
                            if observed.presence_challenge_needed:
                                self._issue_presence_challenge(
                                    session,
                                    row,
                                    engine,
                                    participant_id=q.participant_id,
                                    probe_id=q.probe_id,
                                    location_id=q.location_id,
                                )
                                critical = False
                            if critical and await self._second_decode_agrees(
                                session, inv_id, engine, q, extraction, outcomes, second_decode
                            ):
                                critical = False  # confirmed by an independent decode
                            if critical:
                                self._event(
                                    session,
                                    inv_id,
                                    "BeliefUpdated",
                                    engine.snapshot().model_dump(mode="json"),
                                )
                                self._ask_confirmation(session, row, engine, q)
                                row.version += 1
                                version = row.version
                                continue_planning = False
                        if continue_planning and extraction.wants_to_stop:
                            engine.set_available(q.participant_id, False)
                            self._event(
                                session,
                                inv_id,
                                "ParticipantUnavailable",
                                {"participant_id": q.participant_id, "reason": "asked to stop"},
                            )
                        if continue_planning:
                            await self._schedule(session, row, engine)
                            row.version += 1
                            version = row.version
            except BaseException:
                self._cache.pop(inv_id, None)  # the engine may have been mutated
                raise
            self._cache[inv_id] = (version, engine)
        if challenge_reply is not None:
            passed, message = challenge_reply
            return ChallengeAnswerResult(
                passed=passed, message=message, state=await self.get(inv_id)
            )
        return AnswerResult(observation=obs, extraction=extraction, state=await self.get(inv_id))

    async def reveal(self, inv_id: str) -> InvestigationState:
        async with self._lock(inv_id), self.db.transaction() as session:
            row = await self._load_row(session, inv_id, lock=True)
            if row.status == InvestigationStatus.CLOSED.value:
                pass
            elif row.status not in {s.value for s in TERMINAL_STATUSES}:
                raise ApiError(
                    409,
                    "INVESTIGATION_ACTIVE",
                    "ground truth is revealed only after a decision or abstention",
                )
            else:
                await self.sim.close(row.scenario_id)
                reveal = await self.sim.reveal(row.scenario_id)
                pack = self.pack(row.pack_id)
                true_hyps = [f"{f.component_id}.{f.mode}" for f in reveal.fault_spec.faults]
                true_set = {pack.decision_of.get(h, "UNMODELLED") for h in true_hyps or [NO_FAULT]}
                if len(true_set) > 1:
                    true_set.add(MULTIPLE_FAULTS)  # the engine's name for "several teams"
                true_decisions = sorted(true_set)
                outcome = row.outcome or {}
                concluded = outcome.get("decision_class")
                abstained = outcome.get("kind") == PlanKind.ABSTAIN.value
                cmp = GroundTruthComparison(
                    reveal=reveal,
                    true_decision_classes=true_decisions,
                    concluded_decision=concluded,
                    abstained=abstained,
                    correct=None if abstained else concluded in true_decisions,
                )
                row.ground_truth = cmp.model_dump(mode="json")
                row.status = InvestigationStatus.CLOSED.value
                row.version += 1
                self._event(session, inv_id, "GroundTruthRevealed", row.ground_truth)
        return await self.get(inv_id)

    # -- queries ---------------------------------------------------------------------------------

    async def get(self, inv_id: str) -> InvestigationState:
        # The lock prevents reading a cached engine that a command has mutated but not committed.
        async with self._lock(inv_id), self.db.read() as session:
            row = await self._load_row(session, inv_id, lock=False)
            engine = await self._engine(session, row)
            snapshot = engine.snapshot()
            # Return the persisted trace that produced the current question or conclusion.
            # Recomputing would differ: asking a question changes that person's effort cost.
            plan_payload = (
                await session.execute(
                    select(EventRow.payload)
                    .where(EventRow.investigation_id == inv_id, EventRow.type == "PlanComputed")
                    .order_by(EventRow.seq.desc())
                    .limit(1)
                )
            ).scalar_one()
            plan = PlanDecision.model_validate(plan_payload)
            req = self._request(row)
            questions = (
                (
                    await session.execute(
                        select(QuestionRow)
                        .where(QuestionRow.investigation_id == inv_id)
                        .order_by(QuestionRow.asked_at)
                    )
                )
                .scalars()
                .all()
            )
            approvals = (
                (
                    await session.execute(
                        select(ApprovalRow)
                        .where(ApprovalRow.investigation_id == inv_id)
                        .order_by(ApprovalRow.requested_at)
                    )
                )
                .scalars()
                .all()
            )
            observations = (
                (
                    await session.execute(
                        select(ObservationRow)
                        .where(ObservationRow.investigation_id == inv_id)
                        .order_by(ObservationRow.committed_at)
                    )
                )
                .scalars()
                .all()
            )
        model = self.model(row.pack_id)
        waiting = [
            self._question_view(model, q)
            for q in questions
            if q.status == QuestionStatus.PENDING.value
        ]
        return InvestigationState(
            id=row.id,
            pack_id=row.pack_id,
            status=InvestigationStatus(row.status),
            created_at=row.created_at,
            report=req.report,
            participants=req.participants,
            sealed_commitment=row.commitment,
            belief=snapshot,
            plan=plan,
            pending_question=waiting[0] if waiting else None,
            pending_questions=waiting,
            max_parallel_calls=int(row.request.get("max_parallel_calls", 1)),
            observations=[
                Observation.model_validate({c: getattr(o, c) for c in Observation.model_fields})
                for o in observations
            ],
            questions_asked=len(questions),
            approvals=[self._approval_view(row.pack_id, a) for a in approvals],
            ground_truth=None
            if row.ground_truth is None
            else GroundTruthComparison.model_validate(row.ground_truth),
        )

    @staticmethod
    def _question_view(model: CompiledModel, q: QuestionRow) -> Question:
        return Question(
            id=q.id,
            action=ProbeAction(
                participant_id=q.participant_id,
                probe_id=q.probe_id,
                location_id=q.location_id,
                requires_move=q.requires_move,
            ),
            language=cast(TemplateLanguage, q.language),
            text=q.text,
            outcomes=[] if q.kind == "challenge" else list(model.outcomes[q.probe_id]),
            status=QuestionStatus(q.status),
            asked_at=q.asked_at,
            kind=q.kind if q.kind in {"confirm", "challenge"} else "probe",
            presence_token_id=q.presence_token_id,
        )

    async def events(self, inv_id: str, after_seq: int, limit: int) -> list[EventEnvelope]:
        async with self.db.read() as session:
            await self._load_row(session, inv_id, lock=False)
            rows = (
                (
                    await session.execute(
                        select(EventRow)
                        .where(EventRow.investigation_id == inv_id, EventRow.seq > after_seq)
                        .order_by(EventRow.seq)
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        return [
            EventEnvelope(
                seq=r.seq,
                investigation_id=r.investigation_id,
                type=r.type,
                payload=r.payload,
                ts=r.ts,
            )
            for r in rows
        ]

    # -- approvals, capabilities and repairs ------------------------------------------------------

    def _approval_view(self, pack_id: str, a: ApprovalRow) -> Approval:
        action = next(x for x in self.pack(pack_id).actions if x.id == a.action)
        return Approval(
            id=a.id,
            action=a.action,
            action_label=action.label,
            target=a.target,
            participant_id=a.participant_id,
            status=ApprovalStatus(a.status),
            risk=action.risk,
            reversible=action.reversible,
            rationale=a.rationale,
            requested_at=a.requested_at,
            approver_id=a.approver_id,
            decided_at=a.decided_at,
        )

    async def request_approval(self, inv_id: str, req: RequestApproval) -> InvestigationState:
        """Ask a human to approve a consequential action that the decision calls for."""
        async with self._lock(inv_id), self.db.transaction() as session:
            row = await self._load_row(session, inv_id, lock=True)
            if row.status != InvestigationStatus.DECIDED.value:
                raise ApiError(409, "NOT_DECIDED", "approval follows a decision")
            pack = self.pack(row.pack_id)
            decision = (row.outcome or {}).get("decision_class")
            action = next((a for a in pack.actions if a.id == req.action), None)
            target = pack.component_by_id.get(req.target)
            if action is None or target is None or target.kind != action.target_kind:
                raise ApiError(422, "INVALID_ACTION", f"{req.action} cannot target {req.target}")
            if decision not in action.decision_classes:
                raise ApiError(
                    409, "ACTION_NOT_INDICATED", f"{req.action} does not follow from {decision}"
                )
            person = next(
                (p for p in self._request(row).participants if p.id == req.participant_id), None
            )
            if person is None:
                raise not_found("participant")
            if not {r.value for r in person.roles} & {r.value for r in action.roles}:
                raise ApiError(403, "ROLE_NOT_PERMITTED", f"{action.id} needs another role")
            probability = (row.outcome or {}).get("decision_probability") or 0.0
            why = (row.outcome or {}).get("reason")
            approval = ApprovalRow(
                id=_id("apr"),
                investigation_id=inv_id,
                action=action.id,
                target=req.target,
                participant_id=person.id,
                status=ApprovalStatus.PENDING.value,
                rationale=f"{decision} at P = {probability:.3f}: {why}",
                requested_at=_now(),
            )
            session.add(approval)
            row.status = InvestigationStatus.AWAITING_APPROVAL.value
            row.version += 1
            self._event(
                session,
                inv_id,
                "ApprovalRequested",
                {
                    "approval_id": approval.id,
                    "action": action.id,
                    "target": req.target,
                    "participant_id": person.id,
                    "risk": action.risk,
                    "reversible": action.reversible,
                },
            )
        return await self.get(inv_id)

    async def decide_approval(
        self,
        inv_id: str,
        approval_id: str,
        decision: ApprovalDecision,
        approver_id: str | None = None,
    ) -> InvestigationState:
        """``approver_id`` is the authenticated approver; it overrides any id in the body."""
        approver = approver_id or decision.approver_id
        if approver is None:
            raise ApiError(422, "APPROVER_REQUIRED", "the approval needs an approver")
        async with self._lock(inv_id), self.db.transaction() as session:
            row = await self._load_row(session, inv_id, lock=True)
            approval = await session.get(ApprovalRow, approval_id, with_for_update=True)
            if approval is None or approval.investigation_id != inv_id:
                raise not_found("approval")
            if approval.status != ApprovalStatus.PENDING.value:
                raise ApiError(409, "APPROVAL_DECIDED", f"approval is {approval.status}")
            approve = decision.decision == "approve"
            approval.status = (ApprovalStatus.APPROVED if approve else ApprovalStatus.DENIED).value
            approval.approver_id, approval.decided_at = approver, _now()
            row.status = (
                InvestigationStatus.ACTING if approve else InvestigationStatus.DECIDED
            ).value
            row.version += 1
            self._event(
                session,
                inv_id,
                "ApprovalDecided",
                {
                    "approval_id": approval_id,
                    "decision": decision.decision,
                    "approver_id": approver,
                    "note": decision.note,
                },
            )
        return await self.get(inv_id)

    async def capability_for(
        self, inv_id: str, approval_id: str, participant_id: str
    ) -> CapabilityGrant:
        """Mint the single capability for an approved action, for its named executor only."""
        async with self._lock(inv_id), self.db.transaction() as session:
            row = await self._load_row(session, inv_id, lock=True)
            approval = await session.get(ApprovalRow, approval_id, with_for_update=True)
            if approval is None or approval.investigation_id != inv_id:
                raise not_found("approval")
            if approval.status != ApprovalStatus.APPROVED.value:
                raise ApiError(409, "NOT_APPROVED", f"approval is {approval.status}")
            if approval.participant_id != participant_id:
                raise ApiError(403, "WRONG_PARTICIPANT", "approved for someone else")
            if approval.capability_jti is not None:
                raise ApiError(409, "CAPABILITY_ISSUED", "the capability was already issued")
            token, claims = mint_capability(
                self._signing_key,
                scenario_id=row.scenario_id,
                investigation_id=inv_id,
                participant_id=participant_id,
                action=approval.action,
                target=approval.target,
            )
            approval.capability_jti = claims.jti
            self._event(
                session,
                inv_id,
                "CapabilityIssued",
                {
                    "approval_id": approval_id,
                    "jti": claims.jti,
                    "expires": claims.exp,
                },
            )
            pack = self.pack(row.pack_id)
            action = next(a for a in pack.actions if a.id == approval.action)
            person = next(p for p in self._request(row).participants if p.id == participant_id)
            lang = person.languages.template_language
            comp = pack.component_by_id[approval.target]
            place = pack.location_by_id[comp.location].label.get(lang) if comp.location else ""
        return CapabilityGrant(
            capability=token,
            expires_at=datetime.fromtimestamp(claims.exp, UTC),
            action=approval.action,
            target=approval.target,
            scenario_id=row.scenario_id,
            sim_url=self.browser_sim_url,
            instructions=action.instructions[lang]
            .replace("{target}", approval.target)
            .replace("{place}", place),
            location_id=comp.location if action.at_target_location else None,
        )

    async def report_intervention(
        self, inv_id: str, report: ReportIntervention
    ) -> InvestigationState:
        """The executor says the action is done: model the repair and plan its verification."""
        async with self._lock(inv_id):
            try:
                async with self.db.transaction() as session:
                    row = await self._load_row(session, inv_id, lock=True)
                    if row.status != InvestigationStatus.ACTING.value:
                        raise ApiError(409, "NOT_ACTING", f"investigation is {row.status}")
                    approval = await session.get(
                        ApprovalRow, report.approval_id, with_for_update=True
                    )
                    if approval is None or approval.investigation_id != inv_id:
                        raise not_found("approval")
                    if approval.participant_id != report.participant_id:
                        raise ApiError(403, "WRONG_PARTICIPANT", "approved for someone else")
                    if approval.capability_jti is None:
                        raise ApiError(409, "NO_CAPABILITY", "no capability was issued")
                    engine = await self._engine(session, row)
                    engine.apply_intervention(
                        approval.action, approval.target, report.participant_id
                    )
                    approval.status = ApprovalStatus.EXECUTED.value
                    self._event(
                        session,
                        inv_id,
                        "InterventionReported",
                        {
                            "approval_id": approval.id,
                            "action": approval.action,
                            "target": approval.target,
                            "participant_id": report.participant_id,
                        },
                    )
                    self._apply_plan(session, row, engine, engine.plan())
                    row.version += 1
                    version = row.version
            except BaseException:
                self._cache.pop(inv_id, None)
                raise
            self._cache[inv_id] = (version, engine)
        return await self.get(inv_id)

    async def participant_token(self, inv_id: str, participant_id: str) -> dict[str, str]:
        async with self.db.read() as session:
            row = await self._load_row(session, inv_id, lock=False)
        if participant_id not in {p.id for p in self._request(row).participants}:
            raise not_found("participant")
        token = mint(self._signing_key, participant_id=participant_id, scenario_id=row.scenario_id)
        return {
            "token": token,
            "scenario_id": row.scenario_id,
            "participant_id": participant_id,
            "sim_url": self.browser_sim_url,
        }

    async def pending_question(
        self, inv_id: str, question_id: str, participant_id: str | None = None
    ) -> PendingQuestion:
        """The pending question and its addressee, validated before any paid voice call."""
        async with self.db.read() as session:
            row = await self._load_row(session, inv_id, lock=False)
            q = await session.get(QuestionRow, question_id)
        if q is None or q.investigation_id != inv_id:
            raise not_found("question")
        if row.status not in {st.value for st in ANSWERABLE_STATUSES}:
            raise ApiError(409, "INVESTIGATION_NOT_ACTIVE", f"investigation is {row.status}")
        if q.status != QuestionStatus.PENDING.value:
            raise ApiError(409, "QUESTION_NOT_PENDING", _not_pending(q.status))
        if participant_id is not None and q.participant_id != participant_id:
            raise ApiError(
                403, "WRONG_PARTICIPANT", "question was addressed to another participant"
            )
        person = next(p for p in self._request(row).participants if p.id == q.participant_id)
        return PendingQuestion(
            id=q.id,
            text=q.text,
            # The question was rendered in the participant's registered template language.
            language=person.languages.template_language,
            probe_id=q.probe_id,
            participant=person,
            pack=self.pack(row.pack_id),
            scenario_id=row.scenario_id,
            kind=q.kind,
            presence_token_id=q.presence_token_id,
        )

    async def record_consent(
        self, inv_id: str, participant_id: str, consented: bool, reason: str
    ) -> InvestigationState:
        """Log a call's consent outcome. Anything but a yes takes the person out of the
        investigation: their pending question is cancelled and the engine re-plans without them.

        Replay is unchanged in kind: ``ParticipantUnavailable`` already drives the engine, and
        ``ConsentRecorded`` / ``QuestionCancelled`` only record what happened.
        """
        async with self._lock(inv_id):
            try:
                async with self.db.transaction() as session:
                    row = await self._load_row(session, inv_id, lock=True)
                    if participant_id not in {p.id for p in self._request(row).participants}:
                        raise not_found("participant")
                    engine = await self._engine(session, row)
                    self._event(
                        session,
                        inv_id,
                        "ConsentRecorded",
                        {
                            "participant_id": participant_id,
                            "consented": consented,
                            "reason": reason,
                        },
                    )
                    row.version += 1
                    version = row.version
                    active = row.status in {st.value for st in ANSWERABLE_STATUSES}
                    if not consented and active and engine.participants[participant_id].available:
                        engine.set_available(participant_id, False)
                        self._event(
                            session,
                            inv_id,
                            "ParticipantUnavailable",
                            {"participant_id": participant_id, "reason": reason},
                        )
                        pending = (
                            (
                                await session.execute(
                                    select(QuestionRow).where(
                                        QuestionRow.investigation_id == inv_id,
                                        QuestionRow.participant_id == participant_id,
                                        QuestionRow.status == QuestionStatus.PENDING.value,
                                    )
                                )
                            )
                            .scalars()
                            .all()
                        )
                        for q in pending:
                            q.status = QuestionStatus.CANCELLED.value
                            self._event(
                                session,
                                inv_id,
                                "QuestionCancelled",
                                {"question_id": q.id, "reason": reason},
                            )
                        if pending:
                            await self._schedule(session, row, engine)
            except BaseException:
                self._cache.pop(inv_id, None)
                raise
            self._cache[inv_id] = (version, engine)
        log.info(
            "consent_recorded",
            investigation_id=inv_id,
            participant_id=participant_id,
            consented=consented,
        )
        return await self.get(inv_id)

    async def scenario_of(self, inv_id: str) -> str:
        async with self.db.read() as session:
            row = await self._load_row(session, inv_id, lock=False)
        return row.scenario_id

    def verify_participant_token(self, token: str) -> ParticipantClaims:
        """Check a participant token this core issued (signature, expiry, audience)."""
        return verify_token(self._signing_key.public_key(), token)

    def evict(self, inv_id: str) -> None:
        self._cache.pop(inv_id, None)

    # -- replay and recovery ----------------------------------------------------------------------

    async def head_seq(self, inv_id: str) -> int:
        """The investigation's latest event ``seq`` (404 if it does not exist)."""
        async with self.db.read() as session:
            await self._load_row(session, inv_id, lock=False)
            head = await session.scalar(
                select(func.max(EventRow.seq)).where(EventRow.investigation_id == inv_id)
            )
        return int(head or 0)

    async def replay(self, inv_id: str, *, warm_cache: bool = False) -> ReplayCheck:
        """Rebuild the engine from the event log alone and compare it with the recorded belief.

        The recorded belief is the last ``BeliefUpdated`` payload, which every command that
        changes the belief appends. Both are compared as canonical JSON, byte for byte.
        """
        async with self._lock(inv_id), self.db.read() as session:
            row = await self._load_row(session, inv_id, lock=False)
            engine, n = await self._rebuild(session, row)
            created = (
                await session.execute(
                    select(EventRow.payload)
                    .where(
                        EventRow.investigation_id == inv_id,
                        EventRow.type == "InvestigationCreated",
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            recorded = (
                await session.execute(
                    select(EventRow.payload)
                    .where(EventRow.investigation_id == inv_id, EventRow.type == "BeliefUpdated")
                    .order_by(EventRow.seq.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if warm_cache:
                self._cache[inv_id] = (row.version, engine)
        replayed = engine.snapshot().model_dump(mode="json")
        return ReplayCheck(
            investigation_id=inv_id,
            status=row.status,
            events_replayed=n,
            replayed=replayed,
            recorded=recorded,
            # Logs written before the version was recorded came from model "1".
            recorded_model_version=str((created or {}).get("engine_model_version", "1")),
        )

    async def open_investigations(self, limit: int = 1000) -> list[str]:
        """Investigations whose story is not over (everything but ``closed``), oldest first."""
        async with self.db.read() as session:
            rows = await session.execute(
                select(InvestigationRow.id)
                .where(InvestigationRow.status != InvestigationStatus.CLOSED.value)
                .order_by(InvestigationRow.created_at)
                .limit(limit)
            )
            return [r for (r,) in rows.all()]

    async def record_engine_error(self, inv_id: str, payload: dict[str, Any]) -> None:
        async with self._lock(inv_id), self.db.transaction() as session:
            await self._load_row(session, inv_id, lock=True)
            self._event(session, inv_id, "EngineError", payload)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


@dataclass(frozen=True)
class ReplayCheck:
    investigation_id: str
    status: str
    events_replayed: int
    replayed: dict[str, Any]
    recorded: dict[str, Any] | None
    recorded_model_version: str = MODEL_VERSION
    current_model_version: str = MODEL_VERSION

    @property
    def engine_changed(self) -> bool:
        """The log was written by a different probability model than the one replaying it."""
        return self.recorded_model_version != self.current_model_version

    @property
    def replayed_sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.replayed)).hexdigest()

    @property
    def recorded_sha256(self) -> str | None:
        if self.recorded is None:
            return None
        return hashlib.sha256(canonical_json(self.recorded)).hexdigest()

    @property
    def identical(self) -> bool:
        return self.recorded is not None and canonical_json(self.replayed) == canonical_json(
            self.recorded
        )
