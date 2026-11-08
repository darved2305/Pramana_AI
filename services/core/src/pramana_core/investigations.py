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
import weakref
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import func, inspect, select
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
    CreateInvestigation,
    CreateScenario,
    CreateSiteInvestigation,
    Directness,
    DisagreementView,
    DocumentedModel,
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
    PresenceCheck,
    PresenceCheckView,
    ProbeAction,
    Question,
    QuestionStatus,
    RepairOption,
    Report,
    ReportIntervention,
    RequestApproval,
    SimParticipant,
    SubmitAnswer,
    TemplateLanguage,
)
from pramana_contracts.tokens import (
    ParticipantClaims,
    capability_live,
    mint,
    mint_capability,
    private_key_from_b64,
)
from pramana_contracts.tokens import verify as verify_token
from pramana_domain import NO_FAULT, DomainPack, load_pack
from pramana_domain.spec_storage import spec_digest
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

from . import ids
from .db import (
    ApprovalRow,
    Database,
    EventRow,
    InvestigationRow,
    ObservationRow,
    QuestionRow,
    current_org,
)
from .errors import ApiError, not_found
from .language.explain import disagreement_view
from .language.extraction import Extractor
from .language.intake import INTAKE_PROBE, parse_report
from .language.presence import read_code
from .language.realize import CONFIRM_PREFIX, realize, realize_challenge
from .observability import log
from .sim_client import SimClient
from .site_models import PinnedModel, StoredModels


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


def _now() -> datetime:
    return datetime.now(UTC)


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def _not_pending(status: str) -> str:
    return {
        QuestionStatus.WITHDRAWN.value: "question was withdrawn: another answer made it pointless",
        QuestionStatus.CANCELLED.value: "question was cancelled",
    }.get(status, "question already answered")


class InvestigationService:
    ENGINE_CACHE_MAX = 32

    def __init__(
        self,
        db: Database,
        sim: SimClient,
        extractor: Extractor,
        signing_key_b64: str,
        engine_config: EngineConfig | None = None,
        browser_sim_url: str = "http://127.0.0.1:8100",
        require_saved_models: bool = False,
    ) -> None:
        self.browser_sim_url = browser_sim_url
        self.db = db
        self.sim = sim
        self.extractor = extractor
        self._signing_key = private_key_from_b64(signing_key_b64)
        self._engine_config = engine_config or EngineConfig()
        self._models: dict[str, CompiledModel] = {}
        self.site_models = StoredModels(db)
        self.require_saved_models = require_saved_models
        # Active callers hold strong references to their lock. Once nobody is using an
        # investigation, its lock can be collected instead of accumulating for process life.
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
        self._cache: OrderedDict[str, tuple[int, Engine]] = OrderedDict()

    # -- helpers ---------------------------------------------------------------------------------

    def model(self, pack_id: str) -> CompiledModel:
        if self.require_saved_models:
            raise not_found("saved site model")
        if pack_id not in self._models:
            try:
                self._models[pack_id] = compile_pack(load_pack(pack_id))
            except (FileNotFoundError, ValueError) as exc:
                raise ApiError(422, "UNKNOWN_PACK", f"unknown pack {pack_id}") from exc
        return self._models[pack_id]

    def pack(self, pack_id: str) -> DomainPack:
        return self.model(pack_id).pack

    def _model_for(self, row: InvestigationRow) -> CompiledModel:
        pinned = inspect(row).info.get("pinned_model")
        if isinstance(pinned, PinnedModel):
            return pinned.compiled
        if row.site_model_id is not None or self.require_saved_models:
            raise not_found("site model")
        return self.model(row.pack_id)

    def _pack_for(self, row: InvestigationRow) -> DomainPack:
        return self._model_for(row).pack

    def _lock(self, inv_id: str) -> asyncio.Lock:
        return self._locks.setdefault(inv_id, asyncio.Lock())

    def _cache_engine(self, inv_id: str, version: int, engine: Engine) -> None:
        self._cache.pop(inv_id, None)
        self._cache[inv_id] = (version, engine)
        while len(self._cache) > self.ENGINE_CACHE_MAX:
            self._cache.popitem(last=False)

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
        org = current_org.get()
        if org is not None:
            stmt = stmt.where(InvestigationRow.org_id == org)
        elif self.require_saved_models:
            raise not_found("investigation")
        if lock:
            stmt = stmt.with_for_update()
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            raise not_found("investigation")
        if row.site_id is not None and row.site_model_id is not None:
            if org is None:
                raise not_found("investigation")
            inspect(row).info["pinned_model"] = await self.site_models.load(
                row.site_id, row.site_model_id
            )
        elif self.require_saved_models or org is not None:
            raise not_found("investigation")
        return row

    async def _engine(self, session: AsyncSession, row: InvestigationRow) -> Engine:
        cached = self._cache.get(row.id)
        if cached is not None and cached[0] == row.version:
            self._cache.move_to_end(row.id)
            return cached[1]
        engine, _ = await self._rebuild(session, row)
        self._cache_engine(row.id, row.version, engine)
        return engine

    async def _rebuild(self, session: AsyncSession, row: InvestigationRow) -> tuple[Engine, int]:
        """A fresh engine built only from the event log; also returns how many events it read."""
        req = self._request(row)
        engine = Engine(self._model_for(row), list(req.participants), self._engine_config)
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
            elif type_ == "QuestionWithdrawn" and "location_id" in payload:
                # Logs written before withdrawals carried the place replay as they ran then.
                engine.question_withdrawn(
                    ProbeAction(
                        participant_id=payload["participant_id"],
                        probe_id=payload["probe_id"],
                        location_id=payload["location_id"],
                        requires_move=bool(payload["requires_move"]),
                    )
                )
            elif type_ == "ObservationConfirmed" and payload.get("agreed") is not None:
                engine.confirm(
                    payload["participant_id"],
                    payload["probe_id"],
                    payload["location_id"],
                    bool(payload["agreed"]),
                )
            elif type_ == "ChallengeIssued":
                engine.set_presence(payload["participant_id"], payload["location_id"], "pending")
            elif type_ == "ChallengeResult":
                engine.set_presence(
                    payload["participant_id"],
                    payload["location_id"],
                    "verified" if payload["passed"] else "failed",
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
        if result.disagreements:
            row_pack = engine.model.pack
            names = {p.spec.id: p.spec.display_name for p in engine.participants.values()}
            for d in result.disagreements:
                view = disagreement_view(row_pack, names, d, obs.id)
                self._event(session, inv_id, "DisagreementExplained", view.model_dump(mode="json"))
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

    def _ask(
        self,
        session: AsyncSession,
        row: InvestigationRow,
        engine: Engine,
        action: ProbeAction,
        parallel: CandidateScore | None = None,
    ) -> None:
        """Address one question to one person and log it."""
        req = self._request(row)
        person = next(p for p in req.participants if p.id == action.participant_id)
        lang = person.languages.template_language
        text = realize(self._pack_for(row), action, lang)
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
        engine.record_question(action.participant_id)
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
        self._event(session, row.id, "QuestionAsked", payload)

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
        actions = [
            ProbeAction(
                participant_id=q.participant_id,
                probe_id=q.probe_id,
                location_id=q.location_id,
                requires_move=q.requires_move,
            )
            for q in pending
        ]
        step = schedule(engine, actions, limit)
        conclusive = step.plan is not None and step.plan.kind != PlanKind.ASK
        for i in step.withdraw:
            q = pending[i]
            q.status = QuestionStatus.WITHDRAWN.value  # schedule() told the engine
            self._event(
                session,
                row.id,
                "QuestionWithdrawn",
                {
                    "question_id": q.id,
                    "participant_id": q.participant_id,
                    "probe_id": q.probe_id,
                    "location_id": q.location_id,
                    "requires_move": q.requires_move,
                    "reason": "the investigation reached a conclusion"
                    if conclusive
                    else "another answer made this question pointless",
                },
            )
        if step.plan is not None:
            self._apply_plan(session, row, engine, step.plan)
        else:
            self._event(session, row.id, "BeliefUpdated", engine.snapshot().model_dump(mode="json"))
        for extra in step.ask:
            self._ask(session, row, engine, extra.action, parallel=extra)

    def _apply_plan(
        self, session: AsyncSession, row: InvestigationRow, engine: Engine, plan: PlanDecision
    ) -> None:
        """Record the plan; ask the next question or conclude."""
        self._event(session, row.id, "BeliefUpdated", engine.snapshot().model_dump(mode="json"))
        self._event(session, row.id, "PlanComputed", plan.model_dump(mode="json"))
        if plan.kind == PlanKind.ASK:
            assert plan.action is not None
            self._ask(session, row, engine, plan.action)
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
        heard = await self.extractor.extract(
            alt,
            outcomes,
            question=q.text,
            words=engine.model.pack.probe_by_id[q.probe_id].outcome_words,
        )
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

    def _ask_challenge(
        self,
        session: AsyncSession,
        row: InvestigationRow,
        engine: Engine,
        asked: QuestionRow,
        obs: Observation,
        token_id: str,
    ) -> None:
        """Ask the same person to read the presence token at the place they reported from."""
        engine.set_presence(asked.participant_id, asked.location_id, "pending")
        lang = cast(TemplateLanguage, asked.language)
        text = realize_challenge(self._pack_for(row), token_id, asked.location_id, lang)
        qid = _id("q")
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
                kind="challenge",
                asked_at=_now(),
            )
        )
        engine.record_question(asked.participant_id)
        self._event(
            session,
            row.id,
            "ChallengeIssued",
            {
                "question_id": qid,
                "observation_id": obs.id,
                "participant_id": asked.participant_id,
                "location_id": asked.location_id,
                "token_id": token_id,
            },
        )
        self._event(session, row.id, "BeliefUpdated", engine.snapshot().model_dump(mode="json"))
        self._event(
            session,
            row.id,
            "QuestionAsked",
            {
                "question_id": qid,
                "action": {
                    "participant_id": asked.participant_id,
                    "probe_id": asked.probe_id,
                    "location_id": asked.location_id,
                    "requires_move": False,
                },
                "language": asked.language,
                "text": text,
                "kind": "challenge",
                "challenges_question": asked.id,
            },
        )

    async def _apply_challenge(
        self,
        session: AsyncSession,
        row: InvestigationRow,
        engine: Engine,
        q: QuestionRow,
        ans: SubmitAnswer,
        extraction: Extraction,
    ) -> Observation:
        """Send the reading to the simulator (which alone knows the value) and record the
        result. A wrong reading, or none ("I can't see it"), fails the check: nobody is
        accused, the answer from that place just keeps counting for little."""
        issued = (
            await session.execute(
                select(EventRow.payload)
                .where(EventRow.investigation_id == row.id, EventRow.type == "ChallengeIssued")
                .order_by(EventRow.seq)
            )
        ).scalars()
        payload = next((p for p in issued if p["question_id"] == q.id), None)
        if payload is None:
            raise ApiError(409, "NOTHING_TO_CHECK", "this presence check was not found")
        reading = read_code(ans.text or "")
        result = await self.sim.check_presence(
            row.scenario_id,
            PresenceCheck(
                participant_id=q.participant_id, token_id=payload["token_id"], answer=reading
            ),
        )
        engine.set_presence(
            q.participant_id, q.location_id, "verified" if result.passed else "failed"
        )
        extraction.evidence.append(f"reading:{reading or '-'}")
        self._event(
            session,
            row.id,
            "ChallengeResult",
            {
                "question_id": q.id,
                "observation_id": payload["observation_id"],
                "participant_id": q.participant_id,
                "location_id": q.location_id,
                "token_id": payload["token_id"],
                "passed": result.passed,
                "reading": reading,
            },
        )
        original = await session.get(ObservationRow, payload["observation_id"])
        if original is None:
            raise ApiError(409, "NOTHING_TO_CHECK", "the answer being checked was not found")
        return Observation.model_validate(
            {c: getattr(original, c) for c in Observation.model_fields}
        )

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

    async def create(
        self, req: CreateInvestigation | CreateSiteInvestigation
    ) -> InvestigationState:
        pinned: PinnedModel | None = None
        if isinstance(req, CreateSiteInvestigation):
            try:
                site_id = ids.decode("site", req.site_id)
            except ValueError as exc:
                raise not_found("site") from exc
            pinned = await self.site_models.pin(site_id, practice=req.practice)
            model = pinned.compiled
            documented = DocumentedModel(
                spec=pinned.documented_spec, sha256=pinned.spec_sha256.hex()
            )
        else:
            if self.require_saved_models:
                raise ApiError(422, "SITE_REQUIRED", "choose a saved site for this investigation")
            model = self.model(req.pack_id)
            spec = model.pack.model_dump(mode="json")
            documented = DocumentedModel(spec=spec, sha256=spec_digest(spec).hex())
        pack = model.pack
        for p in req.participants:
            if p.location_id not in pack.location_by_id:
                raise ApiError(
                    422, "UNKNOWN_LOCATION", f"participant {p.id}: unknown location {p.location_id}"
                )
            unknown = sorted(set(map(str, p.roles)) - set(pack.role_catalogue))
            if unknown:
                raise ApiError(
                    422, "UNKNOWN_ROLE", f"participant {p.id}: this site has no role {unknown[0]}"
                )
        scenario = await self.sim.create_scenario(
            CreateScenario(
                pack_id=pack.pack,
                documented_model=documented,
                seed=req.scenario.seed,
                fault=req.scenario.fault,
                participants=[
                    SimParticipant(
                        id=p.id, location_id=p.location_id, roles=[str(r) for r in p.roles]
                    )
                    for p in req.participants
                ],
            )
        )
        inv_id = ids.new("inv")[1]
        # The requested fault (if any) is NOT stored by the core: only the simulator keeps it.
        stored = req.model_dump(mode="json")
        stored["scenario"] = {"seed": req.scenario.seed, "fault": "sealed"}
        # Everything is simulated today: the shared sandbox, the legacy pack path and
        # practice runs on a site's own model. Live runs will store False here.
        stored["practice"] = (
            pinned is None or pinned.sandbox or bool(getattr(req, "practice", False))
        )
        row = InvestigationRow(
            id=inv_id,
            pack_id=pack.pack,
            site_id=pinned.site_id if pinned else None,
            site_model_id=pinned.model_id if pinned else None,
            status=InvestigationStatus.INVESTIGATING.value,
            scenario_id=scenario.scenario_id,
            commitment=scenario.commitment,
            request=stored,
            version=0,
        )
        if pinned:
            org = current_org.get()
            if org is None:
                raise not_found("organization")
            row.org_id = org
            inspect(row).info["pinned_model"] = pinned
        engine = Engine(model, list(req.participants), self._engine_config)
        async with self._lock(inv_id), self.db.transaction() as session:
            session.add(row)
            await session.flush()
            self._event(
                session,
                inv_id,
                "InvestigationCreated",
                {
                    "pack_id": pack.pack,
                    **(
                        {
                            "site_id": ids.encode("site", pinned.site_id),
                            "site_model_id": ids.encode("model", pinned.model_id),
                            "model_sha256": pinned.spec_sha256.hex(),
                        }
                        if pinned
                        else {}
                    ),
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
        self._cache_engine(inv_id, row.version, engine)
        log.info("investigation_created", investigation_id=inv_id, status=row.status)
        return await self.get(inv_id)

    async def _intake(
        self,
        session: AsyncSession,
        row: InvestigationRow,
        engine: Engine,
        req: CreateInvestigation | CreateSiteInvestigation,
    ) -> None:
        """Map the report to evidence only when it explicitly answers the intake probe."""
        reporter = next(p for p in req.participants if p.id == req.report.reporter_id)
        parsed = await parse_report(
            req.report.text, engine.model.pack, reporter.location_id, self.extractor
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
    ) -> AnswerResult:
        """Record an answer. ``second_decode`` (spoken answers only) returns an independent
        transcript of the same audio; it is called only if the decision hinges on this answer.
        If it reads the same outcome, the answer counts as confirmed without asking again."""
        async with self._lock(inv_id):
            try:
                async with self.db.transaction() as session:
                    row = await self._load_row(session, inv_id, lock=True)
                    q = await session.get(QuestionRow, ans.question_id, with_for_update=True)
                    if q is not None and q.investigation_id != inv_id:
                        q = None  # another investigation's question: not found here
                    if q is not None and q.status == QuestionStatus.WITHDRAWN.value:
                        # An answer racing the conclusion was to a question withdrawn at that
                        # moment: say so, so a call ends that turn quietly instead of failing.
                        raise ApiError(409, "QUESTION_NOT_PENDING", _not_pending(q.status))
                    if row.status not in {st.value for st in ANSWERABLE_STATUSES}:
                        raise ApiError(
                            409, "INVESTIGATION_NOT_ACTIVE", f"investigation is {row.status}"
                        )
                    if q is None:
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
                    outcomes = list(self._model_for(row).outcomes[q.probe_id])
                    if q.kind == "challenge":
                        if ans.text is None:
                            raise ApiError(
                                422,
                                "READING_REQUIRED",
                                "a presence check is answered by reading the label, aloud or typed",
                            )
                        extraction = Extraction(
                            outcome=UNKNOWN_OUTCOME,
                            hedge=Hedge.CERTAIN,
                            directness=Directness.DIRECT,
                            method="rules",
                        )
                    elif ans.text is not None:
                        extraction = await self.extractor.extract(
                            ans.text,
                            outcomes,
                            question=q.text,
                            words=self._model_for(row).pack.probe_by_id[q.probe_id].outcome_words,
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
                    if q.kind == "challenge":
                        obs = await self._apply_challenge(session, row, engine, q, ans, extraction)
                        await self._schedule(session, row, engine)
                        row.version += 1
                        version = row.version
                        continue_planning = False
                    elif q.kind == "confirm":
                        obs = await self._apply_confirmation(session, inv_id, engine, q, extraction)
                        await self._schedule(session, row, engine)
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
                        token = (
                            engine.presence_challenge(ev, observed)
                            if row.request.get("presence_checks")
                            else None
                        )
                        if token is not None:
                            # Check presence before a decision rests on this answer. The
                            # answer counts for little until the check passes, so nothing is
                            # decided on it meanwhile (docs/adr/0014).
                            self._ask_challenge(session, row, engine, q, obs, token)
                            row.version += 1
                            version = row.version
                            continue_planning = False
                        critical = token is None and (
                            ans.modality == Modality.VOICE
                            and observed.used_as_evidence
                            and observed.decision_critical
                        )
                        if critical and await self._second_decode_agrees(
                            session, inv_id, engine, q, extraction, outcomes, second_decode
                        ):
                            critical = False  # confirmed by an independent decode
                        if critical:
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
                        await self._schedule(session, row, engine)
                        row.version += 1
                        version = row.version
            except BaseException:
                self._cache.pop(inv_id, None)  # the engine may have been mutated
                raise
            self._cache_engine(inv_id, version, engine)
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
                pack = self._pack_for(row)
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
                # Seal the log: a digest of every event before the reveal, in order. Replay
                # recomputes it, so a later edit to any of them shows (docs/adr/0003).
                sealed = (
                    await session.execute(
                        select(EventRow.type, EventRow.payload)
                        .where(EventRow.investigation_id == inv_id)
                        .order_by(EventRow.seq)
                    )
                ).all()
                self._event(
                    session,
                    inv_id,
                    "GroundTruthRevealed",
                    {
                        **row.ground_truth,
                        "log": {"sha256": log_digest(sealed), "events": len(sealed)},
                    },
                )
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
            testimony = (
                await session.execute(
                    select(EventRow.type, EventRow.payload)
                    .where(
                        EventRow.investigation_id == inv_id,
                        EventRow.type.in_(
                            ("ChallengeIssued", "ChallengeResult", "DisagreementExplained")
                        ),
                    )
                    .order_by(EventRow.seq)
                )
            ).all()
        checks: dict[str, PresenceCheckView] = {}
        disagreements: list[DisagreementView] = []
        for type_, payload in testimony:
            if type_ == "ChallengeIssued":
                checks[payload["question_id"]] = PresenceCheckView(
                    question_id=payload["question_id"],
                    observation_id=payload["observation_id"],
                    participant_id=payload["participant_id"],
                    location_id=payload["location_id"],
                    token_id=payload["token_id"],
                    status="pending",
                )
            elif type_ == "ChallengeResult" and payload["question_id"] in checks:
                checks[payload["question_id"]] = checks[payload["question_id"]].model_copy(
                    update={"status": "passed" if payload["passed"] else "failed"}
                )
            elif type_ == "DisagreementExplained":
                disagreements.append(DisagreementView.model_validate(payload))
        model = self._model_for(row)
        waiting = [
            self._question_view(model, q)
            for q in questions
            if q.status == QuestionStatus.PENDING.value
        ]
        return InvestigationState(
            id=row.id,
            pack_id=row.pack_id,
            site_id=ids.encode("site", row.site_id) if row.site_id else None,
            site_model_id=ids.encode("model", row.site_model_id) if row.site_model_id else None,
            model_sha256=inspect(row).info["pinned_model"].spec_sha256.hex()
            if row.site_model_id
            else None,
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
            presence_checks_enabled=bool(row.request.get("presence_checks", False)),
            presence_checks=list(checks.values()),
            disagreements=disagreements,
            practice=bool(row.request.get("practice", True)),
            repair_options=self._repair_options(model.pack, row, req.participants),
            observations=[
                Observation.model_validate({c: getattr(o, c) for c in Observation.model_fields})
                for o in observations
            ],
            questions_asked=len(questions),
            approvals=[self._approval_view(model.pack, a) for a in approvals],
            ground_truth=None
            if row.ground_truth is None
            else GroundTruthComparison.model_validate(row.ground_truth),
        )

    @staticmethod
    def _repair_options(
        pack: DomainPack, row: InvestigationRow, people: list[ParticipantSpec]
    ) -> list[RepairOption]:
        """Repairs the site's model allows for the current decision, per specific target."""
        decision = (row.outcome or {}).get("decision_class")
        if row.status != InvestigationStatus.DECIDED.value or not decision:
            return []
        hypotheses = next((d.hypotheses for d in pack.decision_classes if d.id == decision), [])
        options: list[RepairOption] = []
        for act in pack.actions:
            if decision not in act.decision_classes:
                continue
            allowed = {str(r) for r in act.roles}
            for hid in hypotheses:
                cid, _, mode = hid.rpartition(".")
                comp = pack.component_by_id.get(cid)
                if comp is None or comp.kind != act.target_kind or mode != act.fixes:
                    continue
                place = pack.location_by_id.get(comp.location) if comp.location else None
                options.append(
                    RepairOption(
                        action=act.id,
                        action_label=act.label,
                        target=comp.id,
                        target_label=comp.label,
                        place=place.label.en if place else None,
                        risk=act.risk,
                        reversible=act.reversible,
                        participant_ids=[
                            p.id for p in people if allowed & {str(r) for r in p.roles}
                        ],
                        roles=sorted(allowed),
                    )
                )
        return options

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
            kind=cast(Literal["probe", "confirm", "challenge"], q.kind)
            if q.kind in ("confirm", "challenge")
            else "probe",
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

    def _approval_view(self, pack: DomainPack, a: ApprovalRow) -> Approval:
        action = next(x for x in pack.actions if x.id == a.action)
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
            requested_by=a.requested_by,
            approver_id=a.approver_id,
            decided_at=a.decided_at,
        )

    async def request_approval(
        self, inv_id: str, req: RequestApproval, requested_by: str | None = None
    ) -> InvestigationState:
        """Ask a human to approve a consequential action that the decision calls for.
        ``requested_by`` is the signed-in account asking, recorded so it cannot approve."""
        async with self._lock(inv_id), self.db.transaction() as session:
            row = await self._load_row(session, inv_id, lock=True)
            if row.status != InvestigationStatus.DECIDED.value:
                raise ApiError(409, "NOT_DECIDED", "approval follows a decision")
            pack = self._pack_for(row)
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
            if not {str(r) for r in person.roles} & {str(r) for r in action.roles}:
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
                requested_by=requested_by,
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
                    **({"requested_by": requested_by} if requested_by else {}),
                },
            )
        return await self.get(inv_id)

    async def decide_approval(
        self,
        inv_id: str,
        approval_id: str,
        decision: ApprovalDecision,
        approver_id: str | None = None,
        approver_account: str | None = None,
    ) -> InvestigationState:
        """``approver_id`` is the authenticated approver; it overrides any id in the body.
        ``approver_account`` (a signed-in person) may not be the account that asked."""
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
            if approver_account is not None and approval.requested_by == approver_account:
                raise ApiError(
                    403,
                    "SELF_APPROVAL",
                    "the person who asked for this action cannot approve it",
                )
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
            # At most one live capability per approval. Collecting again (a reloaded phone
            # page) returns the same one; once it has expired, a fresh one replaces it, so a
            # slow walk to the panel is not a dead end. Single use is the simulator's ledger.
            live: tuple[str, int] | None = None
            if approval.capability_jti is not None:
                exp = await self._capability_expiry(session, inv_id, approval.capability_jti)
                if exp is not None and capability_live(exp):
                    live = (approval.capability_jti, exp)
            token, claims = mint_capability(
                self._signing_key,
                scenario_id=row.scenario_id,
                investigation_id=inv_id,
                participant_id=participant_id,
                action=approval.action,
                target=approval.target,
                reissue=live,
            )
            if live is None:
                issued: dict[str, Any] = {
                    "approval_id": approval_id,
                    "jti": claims.jti,
                    "expires": claims.exp,
                }
                if approval.capability_jti is not None:
                    issued["replaces"] = approval.capability_jti
                approval.capability_jti = claims.jti
                self._event(session, inv_id, "CapabilityIssued", issued)
            pack = self._pack_for(row)
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

    @staticmethod
    async def _capability_expiry(session: AsyncSession, inv_id: str, jti: str) -> int | None:
        payloads = await session.execute(
            select(EventRow.payload).where(
                EventRow.investigation_id == inv_id, EventRow.type == "CapabilityIssued"
            )
        )
        for payload in payloads.scalars():
            if payload.get("jti") == jti:
                return int(payload["expires"])
        return None

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
            self._cache_engine(inv_id, version, engine)
        return await self.get(inv_id)

    async def participant_token(self, inv_id: str, participant_id: str) -> dict[str, str]:
        async with self.db.read() as session:
            row = await self._load_row(session, inv_id, lock=False)
        if participant_id not in {p.id for p in self._request(row).participants}:
            raise not_found("participant")
        org_id = ids.encode("org", row.org_id) if row.site_model_id else None
        token = mint(
            self._signing_key,
            participant_id=participant_id,
            scenario_id=row.scenario_id,
            organization_id=org_id,
        )
        return {
            "token": token,
            "scenario_id": row.scenario_id,
            "participant_id": participant_id,
            "sim_url": self.browser_sim_url,
            **({"org_id": org_id} if org_id else {}),
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
            pack=self._pack_for(row),
            scenario_id=row.scenario_id,
            kind=q.kind,
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
            self._cache_engine(inv_id, version, engine)
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
                self._cache_engine(inv_id, row.version, engine)
            log = (
                await session.execute(
                    select(EventRow.type, EventRow.payload)
                    .where(EventRow.investigation_id == inv_id)
                    .order_by(EventRow.seq)
                )
            ).all()
        seal_at = next((i for i, (t, _) in enumerate(log) if t == "GroundTruthRevealed"), None)
        seal = log[seal_at][1].get("log") if seal_at is not None else None
        replayed = engine.snapshot().model_dump(mode="json")
        return ReplayCheck(
            investigation_id=inv_id,
            status=row.status,
            events_replayed=n,
            replayed=replayed,
            recorded=recorded,
            # Logs written before the version was recorded came from model "1".
            recorded_model_version=str((created or {}).get("engine_model_version", "1")),
            log_sealed=seal is not None,
            log_intact=None
            if seal is None or seal_at is None
            else seal == {"sha256": log_digest(log[:seal_at]), "events": seal_at},
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


def log_digest(events: Sequence[tuple[str, dict[str, Any]]]) -> str:
    """A hash chain over ``(type, payload)`` in log order: changing, removing, inserting or
    reordering any event changes it."""
    digest = hashlib.sha256(b"pramana-log-v1").digest()
    for type_, payload in events:
        item = canonical_json({"type": type_, "payload": payload})
        digest = hashlib.sha256(digest + hashlib.sha256(item).digest()).digest()
    return digest.hex()


@dataclass(frozen=True)
class ReplayCheck:
    investigation_id: str
    status: str
    events_replayed: int
    replayed: dict[str, Any]
    recorded: dict[str, Any] | None
    recorded_model_version: str = MODEL_VERSION
    current_model_version: str = MODEL_VERSION
    log_sealed: bool = False
    log_intact: bool | None = None

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
