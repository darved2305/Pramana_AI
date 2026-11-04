"""The investigation engine: evidence -> posterior -> next action, decision or abstention.

Pure and deterministic: no I/O, no clock, no randomness. The same participants and the same
sequence of evidence always produce the same plan trace, which makes event replay exact.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from pramana_contracts import (
    UNKNOWN_OUTCOME,
    BeliefSnapshot,
    CandidateScore,
    DecisionBelief,
    Directness,
    Hedge,
    HypothesisBelief,
    InfeasibleAction,
    OutcomePreview,
    ParticipantSpec,
    PlanDecision,
    PlanKind,
    PlanRule,
    ProbeAction,
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
    log_posterior,
)
from .config import EngineConfig
from .model import CompiledModel

SiteKey = tuple[str, str, str]  # (participant_id, probe_id, location_id)


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
    """Ids of earlier evidence sites that no single modelled cause can reconcile with this one."""
    surprise_bits: float | None


@dataclass
class _Action:
    participant: ParticipantState
    site: int
    probe_id: str
    location_id: str
    requires_move: bool
    cost_s: float
    lik: FloatArray = field(repr=False)


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
        self._evidence: dict[SiteKey, Evidence] = {}
        self._log_terms = np.zeros(len(model.hypotheses), dtype=np.float64)

    # -- evidence ----------------------------------------------------------------------------

    def reliability(self, skill: Skill, probe_id: str) -> float:
        pclass = self.model.pack.probe_by_id[probe_id].probe_class
        return self.cfg.reliability[(skill, pclass)]

    def _weight(self, ev: Evidence) -> float:
        w = self.cfg.hedge_weight[ev.hedge]
        if ev.directness == Directness.HEARSAY:
            w *= self.cfg.hearsay_factor
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

    def _site_log_lik(self, ev: Evidence, site: int) -> FloatArray:
        ps = self.participants[ev.participant_id]
        lik = likelihood_matrix(
            self.model, site, self.reliability(ps.spec.skill, ev.probe_id), self._weight(ev)
        )
        row = self.model.outcomes[ev.probe_id].index(ev.outcome)
        out: FloatArray = np.log(lik[row])
        return out

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

        p_before = self.posterior()
        key: SiteKey = (ev.participant_id, ev.probe_id, ev.location_id)
        previous = self._evidence.get(key)
        if previous is not None:
            self._log_terms -= self._site_log_lik(previous, site)
            p_before = self.posterior()
        log_lik = self._site_log_lik(ev, site)
        surprise = float(-np.log2(np.exp(log_lik) @ p_before))
        contradiction = self._contradictions(ev, site)
        self._log_terms += log_lik
        self._evidence[key] = ev
        return ObserveResult(True, "committed", previous is not None, contradiction, surprise)

    def _contradictions(self, ev: Evidence, site: int) -> list[str]:
        """Earlier evidence that no modelled single cause can explain together with ``ev``."""
        model = self.model
        row = model.outcomes[ev.probe_id].index(ev.outcome)
        fits_new = model.predictions[:-1, site] == row
        clashes: list[str] = []
        for (pid, probe_id, loc), old in self._evidence.items():
            if (pid, probe_id, loc) == (ev.participant_id, ev.probe_id, ev.location_id):
                continue
            s_old = model.site_index[(probe_id, loc)]
            fits_old = model.predictions[:-1, s_old] == model.outcomes[probe_id].index(old.outcome)
            if not np.any(fits_new & fits_old):
                clashes.append(f"{pid}:{probe_id}@{loc}={old.outcome}")
        return clashes

    def evidence(self) -> list[Evidence]:
        return list(self._evidence.values())

    # -- participant state -------------------------------------------------------------------

    def record_question(self, participant_id: str) -> None:
        self.participants[participant_id].questions_asked += 1

    def set_available(self, participant_id: str, available: bool) -> None:
        self.participants[participant_id].available = available

    # -- belief ------------------------------------------------------------------------------

    def posterior(self) -> FloatArray:
        return log_posterior(self.model, self._log_terms)

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
        return BeliefSnapshot(
            hypotheses=hyps,
            decisions=decisions,
            hypothesis_entropy_bits=entropy_bits(p),
            decision_entropy_bits=entropy_bits(dm),
            open_world_probability=_prob(p[model.open_world_index]),
            map_decision=model.decisions[best_d],
            map_decision_probability=_prob(dm[best_d]),
            expected_loss_now_min=max(0.0, loss_now),
            observations_used=len(self._evidence),
        )

    # -- planning ----------------------------------------------------------------------------

    def _enumerate(self) -> tuple[list[_Action], dict[tuple[str, str], set[str]]]:
        """Feasible actions, and for every site nobody can observe now, why not."""
        model, pack = self.model, self.model.pack
        feasible: list[_Action] = []
        blocked: dict[tuple[str, str], set[str]] = {}
        for pid in sorted(self.participants):
            ps = self.participants[pid]
            for site, (probe_id, loc_id) in enumerate(model.sites):
                probe = pack.probe_by_id[probe_id]
                loc = pack.location_by_id[loc_id]
                reasons: list[str] = []
                if not ps.available:
                    reasons.append("participant unavailable")
                if ps.questions_asked >= ps.spec.question_budget:
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
                if (pid, probe_id, loc_id) in self._evidence:
                    reasons.append("already answered")
                if reasons:
                    if "already answered" not in reasons:
                        blocked.setdefault((probe_id, loc_id), set()).update(reasons)
                    continue
                rel = self.reliability(ps.spec.skill, probe_id)
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
                        likelihood_matrix(model, site, rel, 1.0),
                    )
                )
        observable_now = {(a.probe_id, a.location_id) for a in feasible}
        for key in list(blocked):
            if key in observable_now:
                del blocked[key]
        return feasible, blocked

    def plan(self) -> PlanDecision:
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
        if worth:
            best = candidates[worth[0]]
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
            score=(eig_d + cfg.eta * eig_h) / a.cost_s,
            net_value_min=0.0,
            outcomes=previews,
        )

    def _two_step_net_value(self, actions: list[_Action], p: FloatArray) -> FloatArray:
        """Adaptive two-step value of information minus effort, per first action (minutes).

        ``NV(a) = V(p) - lam*c(a) - sum_o min(V_u(J_ao), min_{b != a} [sum_o' V_u(L_b[o'] J_ao)
        + lam*c(b)*P(o)])`` where ``V_u(u) = min_d sum_h u(h) loss(d, h)`` for an unnormalised
        belief ``u``. Looking two steps ahead avoids stopping on plateaus where no single answer
        can flip the decision but a pair can (single-step EVOI is myopic).
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
