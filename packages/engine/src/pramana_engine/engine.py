"""The investigation engine: evidence -> posterior -> next action, decision or abstention.

Pure and deterministic: no I/O, no clock, no randomness. The same participants and the same
sequence of evidence always produce the same plan trace, which makes event replay exact.

Belief representation (docs/adr/0008):

* **Paths.** A repair can change the world, so the state is a mixture of *paths*: a path is a
  sequence of hypothesis indices, one per *era* (era 0 is before any repair; each repair opens
  a new era). Before any repair there is one path per hypothesis. A repair of a fault ``f``
  splits every path whose current world contains ``f`` into "not fixed" (same world, weight
  ``p_fail``) and "fixed" (the world without ``f``, weight ``1 - p_fail``).
* **Evidence** is stored with its era, and is read against each path's world in that era.
* **Reliability** is unknown per person and probe class. Each group's answers share it; the
  group's likelihood is integrated by Gauss-Jacobi quadrature over a Beta prior. The belief is
  recomputed from the stored evidence, so superseding, confirming and repairs stay exact.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import numpy.typing as npt

from pramana_contracts import (
    UNKNOWN_OUTCOME,
    BeliefSnapshot,
    CandidateScore,
    DecisionBelief,
    Directness,
    Hedge,
    HypothesisBelief,
    InfeasibleAction,
    Modality,
    OutcomePreview,
    ParticipantSpec,
    PlanDecision,
    PlanKind,
    PlanRule,
    ProbeAction,
    RepairState,
    Skill,
)
from pramana_domain import ANY_ROLE, OPEN_WORLD
from pramana_domain.pack import DEVICE_KINDS

from .belief import (
    FloatArray,
    decision_marginal,
    entropy_bits,
    expected_loss,
    likelihood_matrix,
)
from .config import EngineConfig
from .model import OPEN_WORLD_PREDICTION, CompiledModel
from .quadrature import beta_reliability_rule
from .testimony import Disagreement, explain

SiteKey = tuple[str, str, str]  # (participant_id, probe_id, location_id)
Group = tuple[str, str]  # (participant_id, probe class): one shared unknown reliability
Presence = Literal["pending", "verified", "failed"]
"""A presence check of one person at one restricted place (docs/adr/0014)."""


class EvidenceError(ValueError):
    """An observation that cannot be interpreted against the pack or the participant list."""


@dataclass(frozen=True)
class Evidence:
    participant_id: str
    probe_id: str
    location_id: str
    outcome: str
    hedge: Hedge = Hedge.CERTAIN
    directness: Directness = Directness.DIRECT
    modality: Modality = Modality.TEXT


@dataclass
class ParticipantState:
    spec: ParticipantSpec
    location_id: str
    questions_asked: int = 0
    available: bool = True

    @property
    def roles(self) -> set[str]:
        return {r.value for r in self.spec.roles}


@dataclass(frozen=True)
class ObserveResult:
    used_as_evidence: bool
    reason: str
    superseded: bool
    contradiction: list[str]
    """Ids of earlier evidence sites that no modelled cause (single or pair) can reconcile with
    this one, noise-free."""
    surprise_bits: float | None
    decision_critical: bool = False
    """This answer on its own changed the leading decision, or moved its probability by more
    than ``confirm_delta``. A spoken answer like that is worth confirming before relying on it."""
    multiple_faults_suspected: bool = False
    """Taken at face value, the answers so far fit no single fault but do fit a pair."""
    disagreements: tuple[Disagreement, ...] = ()
    """Earlier answers by other people to the same probe with a different outcome, each with
    the engine's reading of it: both right (a cause that affects only one place) or one
    mistaken, and how likely each is (``testimony.explain``)."""


@dataclass(frozen=True)
class _Entry:
    era: int
    key: SiteKey
    ev: Evidence
    site: int
    group: Group


@dataclass
class _Action:
    participant: ParticipantState
    site: int
    probe_id: str
    location_id: str
    requires_move: bool
    cost_s: float
    lik: FloatArray = field(repr=False)


@dataclass(frozen=True)
class _Belief:
    weights: FloatArray
    """[P] normalised posterior weight of each path."""
    mean_reliability: dict[Group, FloatArray]
    """Per group with evidence: [P] posterior mean reliability under each path."""


@dataclass
class _Repair:
    action: str
    target: str
    era: int
    diagnosis_sites: set[tuple[str, str]]


class Engine:
    def __init__(
        self,
        model: CompiledModel,
        participants: list[ParticipantSpec],
        config: EngineConfig | None = None,
    ) -> None:
        self.model = model
        self.cfg = config or EngineConfig()
        self.participants: dict[str, ParticipantState] = {}
        for spec in participants:
            if spec.location_id not in model.pack.location_by_id:
                raise EvidenceError(f"participant {spec.id}: unknown location {spec.location_id}")
            self.participants[spec.id] = ParticipantState(
                spec, spec.location_id, available=spec.available
            )
        n = len(model.hypotheses)
        self._entries: list[_Entry] = []
        self._rows: npt.NDArray[np.int64] = np.arange(n, dtype=np.int64)[:, None]
        self._logw: FloatArray = np.log(model.prior)
        self._fixed = np.zeros(n, dtype=bool)
        self._repair: _Repair | None = None
        self._belief_cache: _Belief | None = None
        self._presence: dict[tuple[str, str], Presence] = {}

    # -- reliability -------------------------------------------------------------------------

    def reliability(self, skill: Skill, probe_id: str) -> float:
        """Prior mean reliability for a skill and the probe's class."""
        pclass = self.model.pack.probe_by_id[probe_id].probe_class
        return self.cfg.reliability[(skill, pclass)]

    def _group(self, participant_id: str, probe_id: str) -> Group:
        return (participant_id, self.model.pack.probe_by_id[probe_id].probe_class)

    def _rule(self, group: Group) -> tuple[FloatArray, FloatArray]:
        """(reliability nodes, log weights) of the group's prior."""
        pid, pclass = group
        mean = self.cfg.reliability[(self.participants[pid].spec.skill, pclass)]
        if self.cfg.reliability_model == "fixed":
            return np.asarray([mean]), np.zeros(1)
        nodes, weights = beta_reliability_rule(
            mean, self.cfg.reliability_concentration, self.cfg.quadrature_nodes
        )
        return np.asarray(nodes), np.log(np.asarray(weights))

    def effective_reliability(
        self, participant_id: str, probe_id: str, mask: npt.NDArray[np.bool_] | None = None
    ) -> FloatArray:
        """[H] E[reliability | current hypothesis, answers so far] for this person and probe.

        The answer model is linear in the reliability, so the predictive distribution of their
        next answer is exactly the likelihood evaluated at this mean.
        """
        group = self._group(participant_id, probe_id)
        nodes, logw = self._rule(group)
        prior_mean = float(np.exp(logw) @ nodes)
        n = len(self.model.hypotheses)
        belief = self._belief()
        rbar = belief.mean_reliability.get(group)
        if rbar is None:
            return np.full(n, prior_mean)
        w = belief.weights if mask is None else np.where(mask, belief.weights, 0.0)
        cur = self._rows[:, -1]
        ph = np.bincount(cur, weights=w, minlength=n)
        num = np.bincount(cur, weights=w * rbar, minlength=n)
        out = np.full(n, prior_mean)
        nz = ph > 0
        out[nz] = num[nz] / ph[nz]
        return out

    # -- evidence ----------------------------------------------------------------------------

    def _weight(self, ev: Evidence) -> float:
        w = self.cfg.hedge_weight[ev.hedge]
        if ev.directness == Directness.HEARSAY:
            w *= self.cfg.hearsay_factor
        if ev.modality == Modality.VOICE:
            w *= self.cfg.voice_weight
        unproven = self._presence.get((ev.participant_id, ev.location_id)) in ("pending", "failed")
        if unproven and self.model.pack.probe_by_id[ev.probe_id].kind not in DEVICE_KINDS:
            w *= self.cfg.presence_unverified_weight
        return w

    def _validate(self, ev: Evidence) -> int:
        ps = self.participants.get(ev.participant_id)
        if ps is None:
            raise EvidenceError(f"unknown participant {ev.participant_id}")
        site = self.model.site_index.get((ev.probe_id, ev.location_id))
        if site is None:
            raise EvidenceError(f"probe {ev.probe_id} cannot be observed at {ev.location_id}")
        allowed = (*self.model.outcomes[ev.probe_id], UNKNOWN_OUTCOME)
        if ev.outcome not in allowed:
            raise EvidenceError(f"outcome {ev.outcome!r} not in {list(allowed)}")
        return site

    @property
    def _era(self) -> int:
        return int(self._rows.shape[1]) - 1

    def _entry_log_lik(self, e: _Entry, nodes: FloatArray) -> FloatArray:
        """[K, P] log P(answer | path's world in the entry's era, reliability node)."""
        model = self.model
        pred = model.predictions[self._rows[:, e.era], e.site]
        m = len(model.outcomes[e.ev.probe_id])
        o = model.outcomes[e.ev.probe_id].index(e.ev.outcome)
        w = self._weight(e.ev)
        hit = (pred == o)[None, :]
        base = np.where(hit, nodes[:, None], ((1.0 - nodes) / (m - 1))[:, None])
        lik = w * base + (1.0 - w) / m
        lik[:, pred == OPEN_WORLD_PREDICTION] = 1.0 / m
        out: FloatArray = np.log(lik)
        return out

    def _belief(self) -> _Belief:
        if self._belief_cache is not None:
            return self._belief_cache
        total = self._logw.copy()
        groups: dict[Group, list[_Entry]] = {}
        for e in self._entries:
            groups.setdefault(e.group, []).append(e)
        rbar: dict[Group, FloatArray] = {}
        for g in sorted(groups):
            nodes, logq = self._rule(g)
            s = np.zeros((len(nodes), len(total)))
            for e in groups[g]:
                s += self._entry_log_lik(e, nodes)
            a = logq[:, None] + s
            mx = a.max(axis=0)
            lse = mx + np.log(np.exp(a - mx).sum(axis=0))
            total += lse
            rbar[g] = nodes @ np.exp(a - lse)
        w = np.exp(total - float(np.max(total)))
        self._belief_cache = _Belief(w / w.sum(), rbar)
        return self._belief_cache

    def _changed(self) -> None:
        self._belief_cache = None

    def _add(self, ev: Evidence, site: int) -> None:
        key: SiteKey = (ev.participant_id, ev.probe_id, ev.location_id)
        group = self._group(ev.participant_id, ev.probe_id)
        self._entries.append(_Entry(self._era, key, ev, site, group))
        self._changed()

    def _pop_current(self, key: SiteKey) -> _Entry | None:
        """Remove and return this person's earlier answer to the same site in this era."""
        for i, e in enumerate(self._entries):
            if e.key == key and e.era == self._era:
                del self._entries[i]
                self._changed()
                return e
        return None

    def observe(self, ev: Evidence) -> ObserveResult:
        """Apply one answer. Unknown outcomes and participants' conclusions are not evidence."""
        site = self._validate(ev)
        ps = self.participants[ev.participant_id]
        probe = self.model.pack.probe_by_id[ev.probe_id]
        if probe.kind not in DEVICE_KINDS:
            ps.location_id = ev.location_id  # they went there to look
        if ev.outcome == UNKNOWN_OUTCOME:
            return ObserveResult(False, "outcome unknown", False, [], None)
        if ev.directness == Directness.ASSUMPTION:
            return ObserveResult(
                False, "participant conclusion, not an observation", False, [], None
            )
        key: SiteKey = (ev.participant_id, ev.probe_id, ev.location_id)
        if self._repair is not None:
            previous = self._pop_current(key)
            before = self.p_fixed()
            self._add(ev, site)
            reason = f"after repair: P(fixed) {before:.3f} -> {self.p_fixed():.3f}"
            return ObserveResult(True, reason, previous is not None, [], None)

        previous = self._pop_current(key)
        p_before = self.posterior()
        lik = likelihood_matrix(
            self.model,
            site,
            self.effective_reliability(ev.participant_id, ev.probe_id),
            self._weight(ev),
        )
        row = self.model.outcomes[ev.probe_id].index(ev.outcome)
        surprise = float(-np.log2(lik[row] @ p_before))
        contradiction = self._contradictions(ev, site)
        dm_before = decision_marginal(self.model, p_before)[:-1]
        self._add(ev, site)
        dm_after = decision_marginal(self.model, self.posterior())[:-1]
        d_after = int(np.argmax(dm_after))
        critical = d_after != int(np.argmax(dm_before)) or (
            abs(float(dm_after[d_after] - dm_before[d_after])) > self.cfg.confirm_delta
        )
        return ObserveResult(
            True,
            "committed",
            previous is not None,
            contradiction,
            surprise,
            critical,
            self._only_pairs_fit(),
            self._disagreements(ev),
        )

    def _disagreements(self, ev: Evidence) -> tuple[Disagreement, ...]:
        """Other people's answers in this era to the same probe that differ from ``ev``."""
        post = self.posterior()
        new = (ev.participant_id, ev.probe_id, ev.location_id, ev.outcome)
        out = []
        for e in self._current_entries():
            if (
                e.ev.participant_id == ev.participant_id
                or e.ev.probe_id != ev.probe_id
                or e.ev.outcome == ev.outcome
            ):
                continue
            earlier = (e.ev.participant_id, e.ev.probe_id, e.ev.location_id, e.ev.outcome)
            out.append(explain(self.model, post, earlier, new))
        return tuple(out)

    # -- presence ------------------------------------------------------------------------------

    def presence_challenge(self, ev: Evidence, result: ObserveResult) -> str | None:
        """The presence token to check ``ev`` with before relying on it, or ``None``.

        Asked when a decision-critical answer is about what is seen in a restricted place the
        person had to go to (they are not registered there), the place has a presence token,
        and this person has not been checked there yet. A claim of having gone somewhere is the
        cheapest lie to tell and the hardest to notice (scenario S7).
        """
        pack = self.model.pack
        token = pack.presence_token_at(ev.location_id)
        ps = self.participants[ev.participant_id]
        if (
            token is None
            or not result.used_as_evidence
            or not result.decision_critical
            or self._repair is not None
            or pack.probe_by_id[ev.probe_id].kind in DEVICE_KINDS
            or not pack.location_by_id[ev.location_id].restricted
            or ps.spec.location_id == ev.location_id
            or (ev.participant_id, ev.location_id) in self._presence
        ):
            return None
        return token.id

    def set_presence(self, participant_id: str, location_id: str, state: Presence) -> None:
        """Record a presence check. While it is pending, and after it fails, what the person
        reports seeing at that place counts at ``presence_unverified_weight``; once it passes
        it counts in full. A failed check also means they are not there, so they are planned
        as still at their registered place."""
        ps = self.participants.get(participant_id)
        if ps is None:
            raise EvidenceError(f"unknown participant {participant_id}")
        if location_id not in self.model.pack.location_by_id:
            raise EvidenceError(f"unknown location {location_id}")
        self._presence[(participant_id, location_id)] = state
        if state == "failed" and ps.location_id == location_id:
            ps.location_id = ps.spec.location_id
        self._changed()

    def presence(self, participant_id: str, location_id: str) -> Presence | None:
        return self._presence.get((participant_id, location_id))

    def confirm(self, participant_id: str, probe_id: str, location_id: str, agreed: bool) -> None:
        """Apply a confirmation of an earlier spoken answer.

        Agreement means two independent recognitions of the same reading matched, so the
        speech-recognition discount is removed (the person's own reliability still applies).
        Disagreement means at least one was misheard: the earlier answer is discarded.
        """
        key: SiteKey = (participant_id, probe_id, location_id)
        matches = [i for i, e in enumerate(self._entries) if e.key == key]
        if not matches:
            raise EvidenceError("nothing to confirm for that participant, probe and place")
        i = max(matches, key=lambda j: (self._entries[j].era, j))
        old = self._entries[i]
        if agreed:
            ev = old.ev
            confirmed = Evidence(
                ev.participant_id,
                ev.probe_id,
                ev.location_id,
                ev.outcome,
                ev.hedge,
                ev.directness,
                Modality.TEXT,
            )
            self._entries[i] = _Entry(old.era, old.key, confirmed, old.site, old.group)
        else:
            del self._entries[i]
        self._changed()

    def _current_entries(self) -> list[_Entry]:
        return [e for e in self._entries if e.era == self._era]

    def _contradictions(self, ev: Evidence, site: int) -> list[str]:
        """Earlier evidence that no modelled cause (single, pair or none) explains with ``ev``."""
        model = self.model
        row = model.outcomes[ev.probe_id].index(ev.outcome)
        cur = self._rows[:, -1]
        known = np.unique(cur[cur != model.open_world_index])
        fits_new = model.predictions[known, site] == row
        clashes: list[str] = []
        for e in self._current_entries():
            if e.key == (ev.participant_id, ev.probe_id, ev.location_id):
                continue
            o = model.outcomes[e.ev.probe_id].index(e.ev.outcome)
            fits_old = model.predictions[known, e.site] == o
            if not np.any(fits_new & fits_old):
                pid, probe_id, loc = e.key
                clashes.append(f"{pid}:{probe_id}@{loc}={e.ev.outcome}")
        return clashes

    def _only_pairs_fit(self) -> bool:
        """Taken at face value, do the answers in this era fit a pair but no single fault?"""
        model = self.model
        entries = self._current_entries()
        if not entries:
            return False
        ok = np.ones(len(model.hypotheses), dtype=bool)
        for e in entries:
            o = model.outcomes[e.ev.probe_id].index(e.ev.outcome)
            ok &= model.predictions[:, e.site] == o
        sizes = np.asarray([-1 if h.faults is None else len(h.faults) for h in model.hypotheses])
        return bool(np.any(ok & (sizes == 2)) and not np.any(ok & (sizes >= 0) & (sizes <= 1)))

    def evidence(self) -> list[Evidence]:
        return [e.ev for e in self._entries]

    # -- repairs -------------------------------------------------------------------------------

    def apply_intervention(
        self, action_id: str, target: str, participant_id: str | None = None
    ) -> None:
        """A repair was carried out. Split each world it could change into fixed / not fixed.

        A repair can fail (the breaker trips again, the reset did not hold), so every path whose
        current world contains the repaired fault splits into "not fixed" (weight ``p``, same
        world) and "fixed" (weight ``1 - p``, the world without that fault; for a pair, the
        other fault remains). Answers from earlier eras count the same in both branches.
        """
        if self._repair is not None:
            raise EvidenceError("only one repair per investigation is modelled at a time")
        model, pack = self.model, self.model.pack
        action = next((a for a in pack.actions if a.id == action_id), None)
        comp = pack.component_by_id.get(target)
        if action is None or comp is None or comp.kind != action.target_kind:
            raise EvidenceError(f"{action_id} cannot target {target}")
        repaired = (target, action.fixes)
        if participant_id is not None and comp.location is not None:
            self.participants[participant_id].location_id = comp.location  # they were there
        p_fail = self.cfg.repair_failure_prior
        rows: list[npt.NDArray[np.int64]] = []
        logw: list[float] = []
        fixed: list[bool] = []
        for path, cur in enumerate(self._rows[:, -1]):
            hyp = model.hypotheses[int(cur)]
            here = self._rows[path]
            if hyp.faults is None or repaired not in hyp.faults:
                rows.append(np.append(here, cur))
                logw.append(float(self._logw[path]))
                fixed.append(False)
                continue
            remaining = frozenset(f for f in hyp.faults if f != repaired)
            rows.append(np.append(here, cur))
            logw.append(float(self._logw[path]) + float(np.log(p_fail)))
            fixed.append(False)
            rows.append(np.append(here, model.fault_index[remaining]))
            logw.append(float(self._logw[path]) + float(np.log(1.0 - p_fail)))
            fixed.append(not remaining)
        self._repair = _Repair(
            action=action_id,
            target=target,
            era=self._era + 1,
            diagnosis_sites={(e.ev.probe_id, e.ev.location_id) for e in self._entries},
        )
        self._rows = np.asarray(rows, dtype=np.int64)
        self._logw = np.asarray(logw)
        self._fixed = np.asarray(fixed, dtype=bool)
        self._changed()

    def reopen(self) -> None:
        """Verification showed the repair did not resolve the problem: resume diagnosis.

        Conditioning on "not resolved" drops the fully fixed paths and keeps the rest. Every
        answer given after the repair is already read against each remaining world (the
        unrepaired one, or for a pair whose one fault was cleared, the other fault alone), so
        the alternatives the repair could not explain are promoted.
        """
        if self._repair is None:
            raise EvidenceError("there is no repair to reopen")
        keep = ~self._fixed
        self._rows = self._rows[keep]
        self._logw = self._logw[keep]
        self._fixed = np.zeros(len(self._logw), dtype=bool)
        self._repair = None
        self._changed()

    def p_fixed(self) -> float:
        """P(symptoms resolved): the repaired fault was the whole cause and the repair held."""
        if self._repair is None:
            return 0.0
        return float(self._belief().weights[self._fixed].sum())

    # -- participant state -------------------------------------------------------------------

    def record_question(self, participant_id: str) -> None:
        self.participants[participant_id].questions_asked += 1

    def set_available(self, participant_id: str, available: bool) -> None:
        self.participants[participant_id].available = available

    # -- belief ------------------------------------------------------------------------------

    def _current(self, mask: npt.NDArray[np.bool_] | None = None) -> FloatArray:
        """[H] probability of each hypothesis as the world now is."""
        w = self._belief().weights
        if mask is not None:
            w = np.where(mask, w, 0.0)
        out = np.bincount(self._rows[:, -1], weights=w, minlength=len(self.model.hypotheses))
        return out.astype(np.float64, copy=False)

    def posterior(self) -> FloatArray:
        """[H] posterior. While a repair is being verified: over the cause before the repair."""
        if self._repair is None:
            return self._current()
        before = self._rows[:, self._repair.era - 1]
        out = np.bincount(
            before, weights=self._belief().weights, minlength=len(self.model.hypotheses)
        )
        return out.astype(np.float64, copy=False)

    def snapshot(self) -> BeliefSnapshot:
        model = self.model
        p = self.posterior()
        dm = decision_marginal(model, p)
        best_d = int(np.argmax(dm[:-1]))
        _, loss_now = expected_loss(model, p)
        order = np.lexsort((np.arange(len(p)), -p))
        hyps = [
            HypothesisBelief(
                id=model.hypotheses[i].id,
                label=model.hypotheses[i].label,
                probability=_prob(p[i]),
                decision_class=model.hypotheses[i].decision_class,
            )
            for i in order
        ]
        d_order = np.lexsort((np.arange(len(model.decisions)), -dm[:-1]))
        decisions = [
            DecisionBelief(
                id=model.decisions[i],
                label=model.decision_labels[model.decisions[i]],
                probability=_prob(dm[i]),
            )
            for i in d_order
        ]
        in_repair = self._repair is not None
        post = len(self._current_entries()) if in_repair else 0
        return BeliefSnapshot(
            hypotheses=hyps,
            decisions=decisions,
            hypothesis_entropy_bits=entropy_bits(p),
            decision_entropy_bits=entropy_bits(dm),
            open_world_probability=_prob(p[model.open_world_index]),
            map_decision=model.decisions[best_d],
            map_decision_probability=_prob(dm[best_d]),
            expected_loss_now_min=max(0.0, loss_now),
            observations_used=len(self._entries) - post,
            repair=None
            if self._repair is None
            else RepairState(
                action=self._repair.action,
                target=self._repair.target,
                fixed_probability=_prob(self.p_fixed()),
                post_repair_observations=post,
            ),
        )

    # -- planning ----------------------------------------------------------------------------

    def _enumerate(self) -> tuple[list[_Action], dict[tuple[str, str], set[str]]]:
        """Feasible actions, and for every site nobody can observe now, why not."""
        model, pack = self.model, self.model.pack
        feasible: list[_Action] = []
        blocked: dict[tuple[str, str], set[str]] = {}
        if self._repair is not None:
            answered_keys = {e.key for e in self._current_entries()}
            seen = {(e.ev.probe_id, e.ev.location_id) for e in self._entries if e.era < self._era}
        else:
            answered_keys = {e.key for e in self._entries}
            seen = {(e.ev.probe_id, e.ev.location_id) for e in self._entries}
        reff: dict[tuple[str, str], FloatArray] = {}
        for pid in sorted(self.participants):
            ps = self.participants[pid]
            for site, (probe_id, loc_id) in enumerate(model.sites):
                probe = pack.probe_by_id[probe_id]
                loc = pack.location_by_id[loc_id]
                reasons: list[str] = []
                if not ps.available:
                    reasons.append("participant unavailable")
                extra = self.cfg.verification_extra_questions if self._repair else 0
                if ps.questions_asked >= ps.spec.question_budget + extra:
                    reasons.append("question budget used")
                if not probe.allows(ps.roles):
                    reasons.append(
                        f"needs role {'/'.join(r for r in probe.roles if r != ANY_ROLE)}"
                    )
                walk = 0
                if loc_id != ps.location_id:
                    if probe.kind in DEVICE_KINDS:
                        reasons.append("phone checks are only asked where the person is")
                    elif not set(ps.roles) & {r.value for r in pack.walking_roles}:
                        reasons.append("not asked to walk")
                    else:
                        w = pack.walk_seconds(ps.location_id, loc_id)
                        if w is None:
                            reasons.append("location unreachable")
                        else:
                            walk = w
                if loc.restricted and not set(ps.roles) & {r.value for r in loc.access_roles}:
                    reasons.append(f"no access to {loc_id}")
                if (pid, probe_id, loc_id) in answered_keys:
                    reasons.append("already answered")
                if reasons:
                    if "already answered" not in reasons:
                        blocked.setdefault((probe_id, loc_id), set()).update(reasons)
                    continue
                group = self._group(pid, probe_id)
                if group not in reff:
                    reff[group] = self.effective_reliability(pid, probe_id)
                cost = (
                    (self.cfg.setup_s if ps.questions_asked == 0 else 0.0)
                    + walk
                    + probe.exec_s
                    + self.cfg.fatigue_s * ps.questions_asked
                )
                feasible.append(
                    _Action(
                        ps,
                        site,
                        probe_id,
                        loc_id,
                        walk > 0,
                        cost,
                        likelihood_matrix(model, site, reff[group], 1.0),
                    )
                )
        observable_now = {(a.probe_id, a.location_id) for a in feasible}
        for key in list(blocked):
            # "What would help" must not suggest something that was already observed.
            if key in observable_now or key in seen:
                del blocked[key]
        return feasible, blocked

    def menu(self) -> list[tuple[ProbeAction, float]]:
        """Every action someone available could take now, with its effort cost in seconds.

        Baselines choose from exactly this menu, so every policy faces the same options.
        """
        actions, _ = self._enumerate()
        return [
            (
                ProbeAction(
                    participant_id=a.participant.spec.id,
                    probe_id=a.probe_id,
                    location_id=a.location_id,
                    requires_move=a.requires_move,
                ),
                a.cost_s,
            )
            for a in actions
        ]

    def plan(self) -> PlanDecision:
        if self._repair is not None:
            return self._verification_plan()
        return self._diagnosis_plan()

    def _verification_plan(self) -> PlanDecision:
        """Choose the observation that best separates "fixed" from "not fixed" per second.

        Observations not used during diagnosis get a bonus: a consequence the diagnosis did not
        rely on is a stronger ("risky") test of the repair.
        """
        rep = self._repair
        assert rep is not None
        cfg, model = self.cfg, self.model
        pf = self.p_fixed()
        fixed = self._fixed
        wf, wn = self._current(fixed), self._current(~fixed)
        h0 = _h2(pf)
        actions, blocked = self._enumerate()
        scored: list[CandidateScore] = []
        for a in actions:
            pid = a.participant.spec.id
            rf = self.effective_reliability(pid, a.probe_id, fixed)
            rn = self.effective_reliability(pid, a.probe_id, ~fixed)
            jf = likelihood_matrix(model, a.site, rf, 1.0) @ wf
            jn = likelihood_matrix(model, a.site, rn, 1.0) @ wn
            po = jf + jn
            cond = sum(
                float(p) * _h2(float(f) / float(p)) for f, p in zip(jf, po, strict=True) if p > 0
            )
            mi = max(0.0, h0 - cond)
            unused = (a.probe_id, a.location_id) not in rep.diagnosis_sites
            previews = [
                OutcomePreview(
                    outcome=model.outcomes[a.probe_id][o],
                    probability=_prob(float(po[o])),
                    top_hypothesis="fixed" if jf[o] >= jn[o] else "not_fixed",
                    top_hypothesis_probability=_prob(float(max(jf[o], jn[o]) / po[o])),
                    decision=None,
                    decision_probability=_prob(float(jf[o] / po[o])),
                )
                for o in range(len(po))
                if po[o] > 0
            ]
            scored.append(
                CandidateScore(
                    action=ProbeAction(
                        participant_id=pid,
                        probe_id=a.probe_id,
                        location_id=a.location_id,
                        requires_move=a.requires_move,
                    ),
                    eig_decision_bits=mi,
                    eig_hypothesis_bits=mi,
                    cost_s=a.cost_s,
                    score=mi / a.cost_s * (cfg.verification_unused_bonus if unused else 1.0),
                    net_value_min=0.0,
                    outcomes=previews,
                )
            )
        scored.sort(key=lambda c: -c.score)
        infeasible = self._rank_blocked(blocked, self._current())
        post = len(self._current_entries())

        def end(kind: PlanKind, rule: PlanRule, reason: str) -> PlanDecision:
            return PlanDecision(
                kind=kind,
                action=None,
                decision_class=None,
                decision_probability=_prob(pf),
                reason=reason,
                rule=rule,
                candidates=scored[: cfg.top_candidates],
                infeasible=infeasible,
            )

        what = f"{rep.action} on {rep.target}"
        if post and pf >= cfg.verified_threshold:
            return end(
                PlanKind.VERIFIED,
                "verification_confirmed",
                f"Verified: after {what}, P(fixed) = {pf:.3f} >= {cfg.verified_threshold:.2f} "
                f"from {post} new observation(s).",
            )
        if pf <= cfg.not_fixed_threshold:
            return end(
                PlanKind.NOT_VERIFIED,
                "verification_failed",
                f"Not fixed: after {what}, P(fixed) = {pf:.3f}. Reopen the investigation.",
            )
        useful = [c for c in scored if c.eig_decision_bits >= cfg.verification_min_bits]
        if not useful:
            return end(
                PlanKind.NOT_VERIFIED,
                "verification_inconclusive",
                f"Cannot confirm {what}: P(fixed) = {pf:.3f} and no available observation "
                "would tell fixed from not fixed." + _needs(infeasible),
            )
        best = useful[0]
        act = best.action
        fresh = (act.probe_id, act.location_id) not in rep.diagnosis_sites
        name = self.participants[act.participant_id].spec.display_name
        reason = (
            f"Verify {what}: ask {name} about {act.probe_id} at {act.location_id}: "
            f"{best.eig_decision_bits:.2f} bits about fixed vs not fixed (P(fixed) now {pf:.2f})"
            f"{'; a consequence not used in the diagnosis' if fresh else ''}."
        )
        if best not in scored[: cfg.top_candidates]:
            scored.insert(0, best)
        return PlanDecision(
            kind=PlanKind.ASK,
            action=act,
            decision_class=None,
            decision_probability=_prob(pf),
            reason=reason,
            rule="positive_value",
            candidates=scored[: cfg.top_candidates],
            infeasible=infeasible,
        )

    def _diagnosis_plan(self) -> PlanDecision:
        model, cfg = self.model, self.cfg
        p = self.posterior()
        dm = decision_marginal(model, p)
        d_star = int(np.argmax(dm[:-1]))
        p_d = float(dm[d_star])
        p_ow = float(p[model.open_world_index])
        d_id = model.decisions[d_star]
        actions, blocked = self._enumerate()

        scored = [self._score(a, p) for a in actions]
        net = self._two_step_net_value(actions, p)
        candidates = [
            s.model_copy(update={"net_value_min": float(v)})
            for s, v in zip(scored, net, strict=True)
        ]
        order = sorted(range(len(candidates)), key=lambda i: (-candidates[i].score, i))
        top = [candidates[i] for i in order[: cfg.top_candidates]]
        infeasible = self._rank_blocked(blocked, p)

        def done(
            kind: PlanKind, rule: PlanRule, reason: str, moderate: bool = False
        ) -> PlanDecision:
            decided = kind == PlanKind.DECIDE
            return PlanDecision(
                kind=kind,
                action=None,
                decision_class=d_id if decided else None,
                decision_probability=_prob(p_d),
                moderate_confidence=moderate,
                reason=reason,
                rule=rule,
                candidates=top,
                infeasible=infeasible,
            )

        label = model.decision_labels[d_id]
        if p_ow >= cfg.open_world_abstain:
            return done(
                PlanKind.ABSTAIN,
                "open_world",
                f"The answers fit no modelled cause well (P(unknown cause) = {p_ow:.2f} "
                f">= {cfg.open_world_abstain:.2f}). Escalate to a human expert."
                + _needs(infeasible),
            )
        if p_d >= cfg.tau_hi:
            return done(
                PlanKind.DECIDE, "confident", f"{label}: P = {p_d:.3f} >= {cfg.tau_hi:.2f}."
            )

        worth = [i for i in order if candidates[i].net_value_min > 0 and candidates[i].score > 0]
        if cfg.selection == "net_value":
            # Rank by the same quantity the stopping rule uses: expected loss avoided minus
            # effort (two-step adaptive). Bits per second is the tie-break.
            worth.sort(key=lambda i: (-candidates[i].net_value_min, -candidates[i].score, i))
        if worth:
            best = candidates[worth[0]]
            if worth[0] not in order[: cfg.top_candidates]:
                top = [*top, best]  # the trace must always contain the chosen action
            a = best.action
            ps = self.participants[a.participant_id]
            alt = next((candidates[i] for i in worth[1:]), None)
            reason = (
                f"Ask {ps.spec.display_name} ({'/'.join(ps.roles)}) about {a.probe_id} at "
                f"{a.location_id}: {best.eig_decision_bits:.2f} bits about the decision "
                f"(+{best.eig_hypothesis_bits:.2f} bits about the cause) for about "
                f"{best.cost_s:.0f} s of their time; worth {best.net_value_min:.2f} min of "
                f"expected loss after effort."
            )
            if alt is not None:
                reason += (
                    f" Next best: {alt.action.probe_id} at {alt.action.location_id} by "
                    f"{self.participants[alt.action.participant_id].spec.display_name} "
                    f"({alt.score * 60:.2f} vs {best.score * 60:.2f} bits/min)."
                )
            return PlanDecision(
                kind=PlanKind.ASK,
                action=a,
                decision_class=None,
                decision_probability=_prob(p_d),
                reason=reason,
                rule="positive_value",
                candidates=top,
                infeasible=infeasible,
            )
        if not actions:
            if p_d >= cfg.tau_lo:
                return done(
                    PlanKind.DECIDE,
                    "no_feasible_action",
                    f"{label}: P = {p_d:.3f}. Nobody available can observe anything "
                    f"more; moderate confidence.",
                    moderate=True,
                )
            return done(
                PlanKind.ABSTAIN,
                "no_feasible_action",
                f"Leading option '{label}' has only P = {p_d:.2f} and nobody available "
                f"can make a further observation." + _needs(infeasible),
            )
        if p_d >= cfg.tau_lo:
            return done(
                PlanKind.DECIDE,
                "no_value_confident_enough",
                f"{label}: P = {p_d:.3f}. No remaining question is worth its effort; "
                f"moderate confidence.",
                moderate=True,
            )
        return done(
            PlanKind.ABSTAIN,
            "no_value_low_confidence",
            f"Leading option '{label}' has only P = {p_d:.2f} and no available question "
            f"would change the decision enough to justify the effort." + _needs(infeasible),
        )

    def _score(self, a: _Action, p: FloatArray) -> CandidateScore:
        model, cfg = self.model, self.cfg
        joint = a.lik * p  # [O, H]
        p_o = joint.sum(axis=1)
        h_prior = entropy_bits(p)
        d_prior = entropy_bits(decision_marginal(model, p))
        eig_h = h_prior
        eig_d = d_prior
        previews: list[OutcomePreview] = []
        for o, po in enumerate(p_o):
            if po <= 0:
                continue
            post = joint[o] / po
            dm = decision_marginal(model, post)
            eig_h -= po * entropy_bits(post)
            eig_d -= po * entropy_bits(dm)
            top_h = int(np.argmax(post))
            top_d = int(np.argmax(dm[:-1]))
            previews.append(
                OutcomePreview(
                    outcome=model.outcomes[a.probe_id][o],
                    probability=_prob(po),
                    top_hypothesis=model.hypotheses[top_h].id,
                    top_hypothesis_probability=_prob(post[top_h]),
                    decision=model.decisions[top_d],
                    decision_probability=_prob(dm[top_d]),
                )
            )
        eig_h, eig_d = max(0.0, eig_h), max(0.0, eig_d)  # clamp float round-off
        return CandidateScore(
            action=ProbeAction(
                participant_id=a.participant.spec.id,
                probe_id=a.probe_id,
                location_id=a.location_id,
                requires_move=a.requires_move,
            ),
            eig_decision_bits=eig_d,
            eig_hypothesis_bits=eig_h,
            cost_s=a.cost_s,
            score=(
                (eig_d + cfg.eta * eig_h if cfg.decision_focus else eig_h)
                / (a.cost_s if cfg.cost_aware else 1.0)
            ),
            net_value_min=0.0,
            outcomes=previews,
        )

    def _two_step_net_value(self, actions: list[_Action], p: FloatArray) -> FloatArray:
        """Adaptive two-step value of information minus effort, per first action (minutes).

        ``NV(a) = V(p) - lam*c(a) - sum_o min(V_u(J_ao), min_{b != a} [sum_o' V_u(L_b[o'] J_ao)
        + lam*c(b)*P(o)])`` where ``V_u(u) = min_d sum_h u(h) loss(d, h)`` for an unnormalised
        belief ``u``. Looking two steps ahead avoids stopping on plateaus where no single answer
        can flip the decision but a pair can (single-step EVOI is myopic). The second step uses
        today's effective reliabilities (it does not re-learn a person's reliability from the
        first answer), an approximation that only matters when both answers share a person and
        a probe class.
        """
        n = len(actions)
        if n == 0:
            return np.zeros(0)
        lam = self.cfg.lambda_min_per_s
        o_max = max(a.lik.shape[0] for a in actions)
        h = len(p)
        lik = np.zeros((n, o_max, h))
        for i, a in enumerate(actions):
            lik[i, : a.lik.shape[0]] = a.lik
        cost = np.asarray([a.cost_s for a in actions])
        loss_t = self.model.loss.T  # [H, D]
        v_now = float(np.min(self.model.loss @ p))

        joint = lik * p  # [n, O, H] = J_a
        v_stop = (joint @ loss_t).min(axis=2)  # [n, O] V_u(J_ao)
        p_o = joint.sum(axis=2)  # [n, O]
        # Second step for every (a, o): inner[a, o, b] = sum_o' V_u(L_b[o'] * J_ao)
        inner = np.einsum("boh,aph,hd->apbod", lik, joint, loss_t, optimize=True).min(axis=4)
        inner = inner.sum(axis=3) + lam * cost[None, None, :] * p_o[:, :, None]  # [a, o, b]
        idx = np.arange(n)
        inner[idx, :, idx] = np.inf  # b must differ from a
        cont = inner.min(axis=2) if n > 1 else np.full_like(v_stop, np.inf)
        value_after = np.minimum(v_stop, cont).sum(axis=1)
        out: FloatArray = v_now - lam * cost - value_after
        return out

    # -- parallel questions (docs/adr/0011) ------------------------------------------------------

    def _pending_lik(self, a: ProbeAction) -> FloatArray:
        site = self.model.site_index.get((a.probe_id, a.location_id))
        if site is None or a.participant_id not in self.participants:
            raise EvidenceError(f"unknown question {a.participant_id}:{a.probe_id}@{a.location_id}")
        reff = self.effective_reliability(a.participant_id, a.probe_id)
        return likelihood_matrix(self.model, site, reff, 1.0)

    def _expected_entropies(self, branches: FloatArray) -> tuple[float, float]:
        """(E[H(decision)], E[H(cause)]) in bits over answer combinations.

        ``branches`` is [B, H]: the unnormalised belief after each combination of answers, so a
        row's sum is that combination's predictive probability.
        """
        mass = branches.sum(axis=1)
        keep = mass > 0
        rows, mass = branches[keep], mass[keep]
        post = rows / mass[:, None]
        n_d = len(self.model.decisions) + 1
        onehot = np.zeros((post.shape[1], n_d))
        onehot[np.arange(post.shape[1]), self.model.decision_of] = 1.0
        dm = post @ onehot

        def ent(x: FloatArray) -> FloatArray:
            with np.errstate(divide="ignore", invalid="ignore"):
                terms = np.where(x > 0, x * np.log2(np.where(x > 0, x, 1.0)), 0.0)
            out: FloatArray = -terms.sum(axis=1)
            return out

        return float(mass @ ent(dm)), float(mass @ ent(post))

    def _branches(self, liks: list[FloatArray], p: FloatArray) -> FloatArray:
        """[B, H] unnormalised beliefs for every combination of answers to ``liks``, starting
        from one belief ``p`` [H] or from several branches already [B0, H].

        Different people's answers are independent given the world (their reliabilities are
        separate unknowns), so the joint likelihood is the product.
        """
        b = p[None, :] if p.ndim == 1 else p
        for lik in liks:
            b = (b[:, None, :] * lik[None, :, :]).reshape(-1, b.shape[1])
        return b

    def conditional_gain(
        self, pending: Sequence[ProbeAction], candidate: ProbeAction
    ) -> tuple[float, float]:
        """Bits about the (decision, cause) that ``candidate`` adds once ``pending`` are answered.

        ``I(D; O_c | O_pending)`` and ``I(H; O_c | O_pending)``, with the pending answers still
        unknown: averaged over every combination of them. With nothing pending this is the
        ordinary expected information gain.
        """
        p = self._current()
        base = self._branches([self._pending_lik(a) for a in pending], p)
        hd0, hh0 = self._expected_entropies(base)
        hd1, hh1 = self._expected_entropies(self._branches([self._pending_lik(candidate)], base))
        return max(0.0, hd0 - hd1), max(0.0, hh0 - hh1)

    def parallel_questions(
        self, pending: Sequence[ProbeAction], max_parallel: int
    ) -> list[CandidateScore]:
        """Questions to ask *now*, alongside ``pending``, to people without a question.

        Greedy batch selection by conditional gain: each extra question must be worth asking on
        its own (the same two-step net value test as ``plan``) and add at least
        ``parallel_min_bits`` about the decision given the answers already on their way. Only
        during diagnosis: a repair is verified one observation at a time.
        """
        if self._repair is not None or len(pending) >= max_parallel:
            return []
        cfg = self.cfg
        p = self._current()
        actions, _ = self._enumerate()
        if not actions:
            return []
        net = self._two_step_net_value(actions, p)
        busy = {a.participant_id for a in pending}
        chosen: list[ProbeAction] = list(pending)
        picks: list[CandidateScore] = []
        branches = self._branches([self._pending_lik(a) for a in chosen], p)
        while len(chosen) < max_parallel:
            hd0, hh0 = self._expected_entropies(branches)
            best: tuple[float, int, float, float, FloatArray] | None = None
            for i, a in enumerate(actions):
                pid = a.participant.spec.id
                if pid in busy or net[i] <= 0:
                    continue
                nxt = self._branches([a.lik], branches)
                hd1, hh1 = self._expected_entropies(nxt)
                gd, gh = max(0.0, hd0 - hd1), max(0.0, hh0 - hh1)
                gain = gd if cfg.decision_focus else gh
                if gain < cfg.parallel_min_bits:
                    continue
                value = (gd + cfg.eta * gh if cfg.decision_focus else gh) / (
                    a.cost_s if cfg.cost_aware else 1.0
                )
                if best is None or value > best[0]:
                    best = (value, i, gd, gh, nxt)
            if best is None:
                break
            value, i, gd, gh, branches = best
            a = actions[i]
            act = ProbeAction(
                participant_id=a.participant.spec.id,
                probe_id=a.probe_id,
                location_id=a.location_id,
                requires_move=a.requires_move,
            )
            picks.append(
                CandidateScore(
                    action=act,
                    eig_decision_bits=gd,
                    eig_hypothesis_bits=gh,
                    cost_s=a.cost_s,
                    score=value,
                    net_value_min=float(net[i]),
                    outcomes=[],
                )
            )
            chosen.append(act)
            busy.add(act.participant_id)
        return picks

    def moot(self, pending: Sequence[ProbeAction]) -> list[bool]:
        """For each question in flight: has its answer stopped mattering to the decision?

        A question is moot when, on today's belief, its answer would tell us less than
        ``withdraw_bits`` about the decision. Each one is judged on its own, not given the
        others, so two questions that overlap are not both withdrawn for that reason.
        """
        if self._repair is not None:
            return [False] * len(pending)
        out: list[bool] = []
        for a in pending:
            gd, _ = self.conditional_gain([], a)
            out.append(gd < self.cfg.withdraw_bits)
        return out

    def _rank_blocked(
        self, blocked: dict[tuple[str, str], set[str]], p: FloatArray
    ) -> list[InfeasibleAction]:
        """Observations nobody present can make, ranked by what they would tell us."""
        model = self.model
        ranked: list[tuple[float, str, str, list[str]]] = []
        d_prior = entropy_bits(decision_marginal(model, p))
        for (probe_id, loc), reasons in blocked.items():
            site = model.site_index[(probe_id, loc)]
            joint = likelihood_matrix(model, site, self.cfg.planning_reliability, 1.0) * p
            gain = d_prior
            for po, row in zip(joint.sum(axis=1), joint, strict=True):
                if po > 0:
                    gain -= po * entropy_bits(decision_marginal(model, row / po))
            if gain > 1e-6:
                ranked.append((gain, probe_id, loc, sorted(reasons)))
        ranked.sort(key=lambda r: (-r[0], r[1], r[2]))
        return [
            InfeasibleAction(participant_id="anyone", probe_id=pr, location_id=loc, reasons=rs)
            for _, pr, loc, rs in ranked[: self.cfg.top_infeasible]
        ]


def _h2(p: float) -> float:
    """Binary entropy in bits."""
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return float(-(p * np.log2(p) + (1 - p) * np.log2(1 - p)))


def _needs(infeasible: list[InfeasibleAction]) -> str:
    if not infeasible:
        return ""
    best = infeasible[0]
    return (
        f" Would help: {best.probe_id} at {best.location_id} "
        f"(currently blocked: {'; '.join(best.reasons)})."
    )


def _prob(x: float) -> float:
    return float(min(1.0, max(0.0, x)))


__all__ = ["OPEN_WORLD", "Engine", "Evidence", "EvidenceError", "ObserveResult", "SiteKey"]
