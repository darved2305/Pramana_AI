"""Sealed scenarios: hidden fault state, participant positions, and what each person perceives.

The true fault set lives only here. Each scenario publishes a SHA-256 commitment over the fault
specification and a random salt at creation, so a reveal at the end can be checked against what
was fixed at the start.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import secrets
from dataclasses import dataclass, field
from enum import StrEnum

from pramana_contracts import (
    ActResult,
    Fault,
    FaultSpec,
    MoveResult,
    ObserveResult,
    ParticipantView,
    PresenceTokenView,
    PresenceVerificationResult,
    RevealResult,
    SimParticipant,
    ViewItem,
)
from pramana_contracts.tokens import CapabilityClaims
from pramana_domain import DomainPack, World
from pramana_domain.pack import DEVICE_KINDS


class ScenarioError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


class ScenarioStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


def canonical_fault_spec(spec: FaultSpec) -> str:
    faults = sorted((f.component_id, f.mode) for f in spec.faults)
    return json.dumps({"faults": faults}, separators=(",", ":"))


def commitment_for(scenario_id: str, spec: FaultSpec, salt: str) -> str:
    material = f"{scenario_id}|{canonical_fault_spec(spec)}|{salt}".encode()
    return hashlib.sha256(material).hexdigest()


def draw_fault(pack: DomainPack, seed: int) -> FaultSpec:
    """Sample one fault (or none) in proportion to the pack's priors, reproducibly from ``seed``.

    The simulator's catalogue is the pack's catalogue here. Scenarios with several faults can be
    requested explicitly. The engine models identifiable pairs (docs/adr/0008); masked pairs,
    triples and faults outside the pack remain model mismatch for the benchmark to measure.
    """
    rng = random.Random(seed)
    options: list[FaultSpec] = [
        FaultSpec(faults=[Fault(component_id=c, mode=m)]) for c, m, _ in pack.fault_hypotheses()
    ]
    weights = [fm.prior for _, _, fm in pack.fault_hypotheses()]
    options.append(FaultSpec(faults=[]))
    weights.append(pack.no_fault_prior)
    return rng.choices(options, weights=weights, k=1)[0]


@dataclass
class _Person:
    roles: frozenset[str]
    location_id: str


@dataclass
class Scenario:
    id: str
    pack: DomainPack
    fault_spec: FaultSpec
    salt: str
    commitment: str
    people: dict[str, _Person]
    seed: int = 0
    status: ScenarioStatus = ScenarioStatus.OPEN
    world: World = field(init=False, repr=False)
    used_capabilities: set[str] = field(default_factory=set)
    interventions: list[tuple[str, str, str]] = field(default_factory=list)
    _active_faults: set[tuple[str, str]] = field(default_factory=set)
    _presence_values: dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._active_faults = {(f.component_id, f.mode) for f in self.fault_spec.faults}
        self.world = World(self.pack, frozenset(self._active_faults))
        alphabet = "34679ACDEFHJKMNPQRTUVWXY"
        for token in sorted(self.pack.presence_tokens, key=lambda item: item.id):
            rng = random.Random(f"{self.seed}:{token.id}")
            self._presence_values[token.id] = "".join(
                rng.choice(alphabet) for _ in range(token.length)
            )

    @classmethod
    def create(
        cls, pack: DomainPack, fault: FaultSpec, participants: list[SimParticipant], seed: int = 0
    ) -> Scenario:
        sid = "sc_" + secrets.token_hex(6)
        salt = secrets.token_hex(16)
        people: dict[str, _Person] = {}
        for p in participants:
            if p.location_id not in pack.location_by_id:
                raise ScenarioError(422, "UNKNOWN_LOCATION", f"unknown location {p.location_id}")
            people[p.id] = _Person(frozenset(p.roles), p.location_id)
        try:
            return cls(sid, pack, fault, salt, commitment_for(sid, fault, salt), people, seed)
        except ValueError as exc:  # World rejects faults the pack cannot represent
            raise ScenarioError(422, "UNKNOWN_FAULT", str(exc)) from exc

    # -- participant-facing --------------------------------------------------------------------

    def _person(self, participant_id: str) -> _Person:
        self._require_open()
        person = self.people.get(participant_id)
        if person is None:
            raise ScenarioError(403, "NOT_A_PARTICIPANT", "participant not in this scenario")
        return person

    def _require_open(self) -> None:
        if self.status != ScenarioStatus.OPEN:
            raise ScenarioError(409, "SCENARIO_CLOSED", "scenario is closed")

    def _visible_probes(self, person: _Person) -> list[tuple[str, str]]:
        out = []
        for probe in self.pack.probes:
            if probe.binding_at(person.location_id) is None or not probe.allows(person.roles):
                continue
            out.append((probe.id, probe.label))
        return out

    def view(self, participant_id: str) -> ParticipantView:
        person = self._person(participant_id)
        loc = self.pack.location_by_id[person.location_id]
        items = [
            ViewItem(
                probe_id=pid,
                label=label,
                value=self.world.observe(self.pack.probe_by_id[pid], person.location_id),
            )
            for pid, label in self._visible_probes(person)
        ]
        return ParticipantView(
            scenario_id=self.id,
            participant_id=participant_id,
            location_id=loc.id,
            location_label=loc.label.en,
            items=items,
            reachable_locations=self._reachable(person),
            presence_tokens=[
                PresenceTokenView(
                    token_id=token.id,
                    display_texts={
                        language: template.format(
                            length=token.length, value=self._presence_values[token.id]
                        )
                        for language, template in token.display_templates.items()
                    },
                )
                for token in self.pack.presence_tokens
                if token.location_id == person.location_id
            ],
        )

    def verify_presence(
        self, participant_id: str, token_id: str, answer: str
    ) -> PresenceVerificationResult:
        """Return pass/fail for an operator supplied answer at the participant's current site."""
        self._require_open()
        person = self.people.get(participant_id)
        token = self.pack.presence_token_by_id.get(token_id)
        expected = self._presence_values.get(token_id)
        compact_answer = "".join(char for char in answer.upper() if char.isalnum())
        passed = bool(
            person is not None
            and token is not None
            and expected is not None
            and person.location_id == token.location_id
            and hmac.compare_digest(compact_answer.encode(), expected.encode())
        )
        return PresenceVerificationResult(passed=passed)

    def _can_enter(self, person: _Person, location_id: str) -> bool:
        loc = self.pack.location_by_id[location_id]
        return not loc.restricted or bool(person.roles & {r.value for r in loc.access_roles})

    def _reachable(self, person: _Person) -> list[str]:
        if not person.roles & {r.value for r in self.pack.walking_roles}:
            return []
        return sorted(
            loc.id
            for loc in self.pack.locations
            if loc.id != person.location_id
            and self._can_enter(person, loc.id)
            and self.pack.walk_seconds(person.location_id, loc.id) is not None
        )

    def move(self, participant_id: str, to: str) -> MoveResult:
        person = self._person(participant_id)
        if to not in self.pack.location_by_id:
            raise ScenarioError(422, "UNKNOWN_LOCATION", f"unknown location {to}")
        if to != person.location_id and to not in self._reachable(person):
            raise ScenarioError(403, "MOVE_NOT_ALLOWED", f"cannot move to {to}")
        walk = self.pack.walk_seconds(person.location_id, to) or 0
        person.location_id = to
        return MoveResult(location_id=to, walk_s=walk)

    def observe(self, participant_id: str, probe_id: str) -> ObserveResult:
        """What this person perceives for one probe at their current location (noise-free)."""
        person = self._person(participant_id)
        probe = self.pack.probe_by_id.get(probe_id)
        if probe is None:
            raise ScenarioError(422, "UNKNOWN_PROBE", f"unknown probe {probe_id}")
        if not probe.allows(person.roles):
            raise ScenarioError(403, "ROLE_NOT_PERMITTED", f"{probe_id} not permitted for role")
        if probe.binding_at(person.location_id) is None:
            where = "here" if probe.kind in DEVICE_KINDS else f"at {person.location_id}"
            raise ScenarioError(
                409, "NOT_OBSERVABLE_HERE", f"{probe_id} cannot be observed {where}"
            )
        return ObserveResult(
            probe_id=probe_id,
            location_id=person.location_id,
            value=self.world.observe(probe, person.location_id),
        )

    def act(
        self, participant_id: str, action_id: str, target: str, claims: CapabilityClaims
    ) -> ActResult:
        """Carry out an approved action. Every precondition is checked here, in the world."""
        person = self._person(participant_id)
        if claims.scn != self.id or claims.sub != participant_id:
            raise ScenarioError(403, "CAPABILITY_MISMATCH", "capability is for someone else")
        if claims.act != action_id or claims.tgt != target:
            raise ScenarioError(403, "CAPABILITY_SCOPE", "capability does not cover this action")
        if claims.jti in self.used_capabilities:
            raise ScenarioError(409, "CAPABILITY_USED", "capability already used")
        action = next((a for a in self.pack.actions if a.id == action_id), None)
        comp = self.pack.component_by_id.get(target)
        if action is None or comp is None or comp.kind != action.target_kind:
            raise ScenarioError(422, "INVALID_ACTION", f"{action_id} cannot target {target}")
        if not person.roles & {r.value for r in action.roles}:
            raise ScenarioError(403, "ROLE_NOT_PERMITTED", f"{action_id} needs another role")
        if action.at_target_location and comp.location != person.location_id:
            raise ScenarioError(409, "NOT_AT_TARGET", f"go to {comp.location} first")
        self.used_capabilities.add(claims.jti)
        self._active_faults.discard((target, action.fixes))
        self.world = World(self.pack, frozenset(self._active_faults))
        self.interventions.append((participant_id, action_id, target))
        return ActResult(action=action_id, target=target, performed=True)

    # -- operator / oracle -----------------------------------------------------------------------

    def close(self) -> None:
        self.status = ScenarioStatus.CLOSED

    def reveal(self) -> RevealResult:
        if self.status != ScenarioStatus.CLOSED:
            raise ScenarioError(409, "SCENARIO_OPEN", "close the scenario before revealing it")
        return RevealResult(
            scenario_id=self.id,
            fault_spec=self.fault_spec,
            salt=self.salt,
            commitment=self.commitment,
            commitment_verified=commitment_for(self.id, self.fault_spec, self.salt)
            == self.commitment,
        )
