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
    CapabilityGrant,
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
    Question,
    QuestionStatus,
    Report,
    ReportIntervention,
    RequestApproval,
    SimParticipant,
    SubmitAnswer,
    TemplateLanguage,
)
from pramana_contracts.tokens import mint, mint_capability, private_key_from_b64
from pramana_domain import NO_FAULT, DomainPack, load_pack
from pramana_engine import (
    CompiledModel,
    Engine,
    EngineConfig,
    Evidence,
    EvidenceError,
    ObserveResult,
    compile_pack,
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
from .language.realize import CONFIRM_PREFIX, realize
from .observability import log
from .sim_client import SimClient

INTAKE_PROBE = "internet_works"


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


def _now() -> datetime:
    return datetime.now(UTC)


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


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
                engine.record_question(payload["action"]["participant_id"])
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
            },
        )
        return obs, result

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

    def _apply_plan(
        self, session: AsyncSession, row: InvestigationRow, engine: Engine, plan: PlanDecision
    ) -> None:
        """Record the plan; ask the next question or conclude."""
        self._event(session, row.id, "BeliefUpdated", engine.snapshot().model_dump(mode="json"))
        self._event(session, row.id, "PlanComputed", plan.model_dump(mode="json"))
        if plan.kind == PlanKind.ASK:
            assert plan.action is not None
            req = self._request(row)
            person = next(p for p in req.participants if p.id == plan.action.participant_id)
            lang = person.languages.template_language
            text = realize(self.pack(row.pack_id), plan.action, lang)
            qid = _id("q")
            session.add(
                QuestionRow(
                    id=qid,
                    investigation_id=row.id,
                    participant_id=plan.action.participant_id,
                    probe_id=plan.action.probe_id,
                    location_id=plan.action.location_id,
                    requires_move=plan.action.requires_move,
                    language=lang,
                    text=text,
                    status=QuestionStatus.PENDING.value,
                    asked_at=_now(),
                )
            )
            engine.record_question(plan.action.participant_id)
            self._event(
                session,
                row.id,
                "QuestionAsked",
                {
                    "question_id": qid,
                    "action": plan.action.model_dump(mode="json"),
                    "language": lang,
                    "text": text,
                },
            )
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

    def _ask_confirmation(
        self, session: AsyncSession, row: InvestigationRow, engine: Engine, asked: QuestionRow
    ) -> None:
        """Re-ask the same item-specific question (not "did you say X?"), same person."""
        lang = cast(TemplateLanguage, asked.language)
        qid = _id("q")
        text = CONFIRM_PREFIX[lang] + asked.text
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
                },
            )
            self._event(session, inv_id, "ReportReceived", req.report.model_dump(mode="json"))
            await self._intake(session, row, engine, req)
            self._apply_plan(session, row, engine, engine.plan())
            row.version = 1
        self._cache[inv_id] = (row.version, engine)
        log.info("investigation_created", investigation_id=inv_id, status=row.status)
        return await self.get(inv_id)

    async def _intake(
        self, session: AsyncSession, row: InvestigationRow, engine: Engine, req: CreateInvestigation
    ) -> None:
        """Map the report to evidence only when it explicitly answers the intake probe."""
        reporter = next(p for p in req.participants if p.id == req.report.reporter_id)
        probe = self.pack(req.pack_id).probe_by_id.get(INTAKE_PROBE)
        if probe is None or probe.binding_at(reporter.location_id) is None:
            return
        extraction = await self.extractor.extract(req.report.text, probe.outcomes)
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

    async def answer(self, inv_id: str, ans: SubmitAnswer) -> AnswerResult:
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
                        raise ApiError(409, "QUESTION_NOT_PENDING", "question already answered")
                    if q.participant_id != ans.participant_id:
                        raise ApiError(
                            403,
                            "WRONG_PARTICIPANT",
                            "question was addressed to another participant",
                        )
                    engine = await self._engine(session, row)
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
                        obs = await self._apply_confirmation(session, inv_id, engine, q, extraction)
                        self._apply_plan(session, row, engine, engine.plan())
                        row.version += 1
                        version = row.version
                        continue_planning = False
                    else:
                        obs, observed = self._record_observation(
                            session,
                            inv_id,
                            engine,
                            ev,
                            extraction,
                            question_id=q.id,
                            modality=ans.modality.value,
                            transcript=ans.text,
                        )
                        await self._supersede(session, inv_id, obs)
                        continue_planning = True
                        if (
                            ans.modality == Modality.VOICE
                            and observed.used_as_evidence
                            and observed.decision_critical
                        ):
                            # The decision hinges on one spoken answer, and speech recognition
                            # gives no confidence score: confirm it before relying on it.
                            # The answer did move the belief: record that, so the console and
                            # replay agree with the engine while the confirmation is pending.
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
                        self._apply_plan(session, row, engine, engine.plan())
                        row.version += 1
                        version = row.version
            except BaseException:
                self._cache.pop(inv_id, None)  # the engine may have been mutated
                raise
            self._cache[inv_id] = (version, engine)
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
                true_decisions = sorted(
                    {pack.decision_of.get(h, "UNMODELLED") for h in true_hyps or [NO_FAULT]}
                )
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
        pending = next((q for q in questions if q.status == QuestionStatus.PENDING.value), None)
        model = self.model(row.pack_id)
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
            pending_question=None
            if pending is None
            else Question(
                id=pending.id,
                action={
                    "participant_id": pending.participant_id,
                    "probe_id": pending.probe_id,
                    "location_id": pending.location_id,
                    "requires_move": pending.requires_move,
                },
                language=pending.language,
                text=pending.text,
                outcomes=list(model.outcomes[pending.probe_id]),
                status=QuestionStatus(pending.status),
                asked_at=pending.asked_at,
                kind="confirm" if pending.kind == "confirm" else "probe",
            ),
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
        self, inv_id: str, approval_id: str, decision: ApprovalDecision
    ) -> InvestigationState:
        async with self._lock(inv_id), self.db.transaction() as session:
            row = await self._load_row(session, inv_id, lock=True)
            approval = await session.get(ApprovalRow, approval_id, with_for_update=True)
            if approval is None or approval.investigation_id != inv_id:
                raise not_found("approval")
            if approval.status != ApprovalStatus.PENDING.value:
                raise ApiError(409, "APPROVAL_DECIDED", f"approval is {approval.status}")
            approve = decision.decision == "approve"
            approval.status = (ApprovalStatus.APPROVED if approve else ApprovalStatus.DENIED).value
            approval.approver_id, approval.decided_at = decision.approver_id, _now()
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
                    "approver_id": decision.approver_id,
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
            raise ApiError(409, "QUESTION_NOT_PENDING", "question already answered")
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
        )

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
