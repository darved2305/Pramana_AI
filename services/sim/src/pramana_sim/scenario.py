"""Sealed scenarios: hidden fault state, participant positions, and what each person perceives.

The true fault set lives only here. Each scenario publishes a SHA-256 commitment over the fault
specification and a random salt at creation, so a reveal at the end can be checked against what
was fixed at the start.
"""

from __future__ import annotations

import hashlib
import json
import random
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pramana_contracts import (
    ActResult,
    DocumentedModel,
    Fault,
    FaultSpec,
    MoveResult,
    ObserveResult,
    ParticipantView,
    PresenceCheckResult,
    RevealResult,
    SimParticipant,
    ViewItem,
    ViewLabel,
)
from pramana_contracts.tokens import CapabilityClaims
from pramana_domain import DomainPack, World
from pramana_domain.spec_storage import spec_digest


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


PRESENCE_ALPHABET = "AFHKLMQRXY345679"
"""Characters of a presence-token value: no pair sounds alike when read aloud (no B/D/P/T/V,
no M/N together with 1/I or 0/O), so a correct reading survives speech recognition."""
PRESENCE_LENGTH = 3
PRESENCE_ATTEMPTS = 2
"""Checks allowed per person and token, so the core cannot be used to guess the value."""


def canonical_reading(text: str) -> str:
    return "".join(c for c in text.upper() if c.isascii() and c.isalnum())


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
    status: ScenarioStatus = ScenarioStatus.OPEN
    world: World = field(init=False, repr=False)
    used_capabilities: set[str] = field(default_factory=set)
    interventions: list[tuple[str, str, str]] = field(default_factory=list)
    _active_faults: set[tuple[str, str]] = field(default_factory=set)
    presence_values: dict[str, str] = field(default_factory=dict, repr=False)
    presence_attempts: dict[tuple[str, str], int] = field(default_factory=dict)
    documented_model: DocumentedModel | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.presence_values:
            self.presence_values = {
                t.id: "".join(secrets.choice(PRESENCE_ALPHABET) for _ in range(PRESENCE_LENGTH))
                for t in self.pack.presence_tokens
            }
        self._active_faults = {(f.component_id, f.mode) for f in self.fault_spec.faults}
        self.world = World(self.pack, frozenset(self._active_faults))

    @classmethod
    def create(
        cls,
        pack: DomainPack,
        fault: FaultSpec,
        participants: list[SimParticipant],
        *,
        documented_model: DocumentedModel | None = None,
    ) -> Scenario:
        sid = "sc_" + secrets.token_hex(6)
        salt = secrets.token_hex(16)
        people: dict[str, _Person] = {}
        for p in participants:
            if p.location_id not in pack.location_by_id:
                raise ScenarioError(422, "UNKNOWN_LOCATION", f"unknown location {p.location_id}")
            people[p.id] = _Person(frozenset(p.roles), p.location_id)
        try:
            return cls(
                sid,
                pack,
                fault,
                salt,
                commitment_for(sid, fault, salt),
                people,
                documented_model=documented_model,
            )
        except ValueError as exc:  # World rejects faults the pack cannot represent
            raise ScenarioError(422, "UNKNOWN_FAULT", str(exc)) from exc

    def to_snapshot(self) -> dict[str, object]:
        """Serialize the complete sealed world for local staging recovery."""
        model = self.documented_model
        if model is None:
            spec = self.pack.model_dump(mode="json")
            model = DocumentedModel(spec=spec, sha256=spec_digest(spec).hex())
        return {
            "id": self.id,
            "pack_id": self.pack.pack,
            "documented_model": model.model_dump(mode="json"),
            "fault_spec": self.fault_spec.model_dump(mode="json"),
            "salt": self.salt,
            "commitment": self.commitment,
            "people": {
                participant_id: {
                    "roles": sorted(person.roles),
                    "location_id": person.location_id,
                }
                for participant_id, person in self.people.items()
            },
            "status": self.status.value,
            "used_capabilities": sorted(self.used_capabilities),
            "interventions": [list(item) for item in self.interventions],
            "active_faults": [list(item) for item in sorted(self._active_faults)],
            "presence_values": dict(sorted(self.presence_values.items())),
            "presence_attempts": [
                [participant_id, token_id, attempts]
                for (participant_id, token_id), attempts in sorted(self.presence_attempts.items())
            ],
        }

    @classmethod
    def from_snapshot(cls, pack: DomainPack, snapshot: Mapping[str, Any]) -> Scenario:
        """Restore and validate a local snapshot, including mutable world state."""
        scenario_id = _snapshot_string(snapshot, "id")
        fault = FaultSpec.model_validate(snapshot.get("fault_spec"))
        salt = _snapshot_string(snapshot, "salt")
        commitment = _snapshot_string(snapshot, "commitment")
        if commitment_for(scenario_id, fault, salt) != commitment:
            raise ValueError("stored scenario commitment does not match its fault")

        raw_people = snapshot.get("people")
        if not isinstance(raw_people, dict):
            raise ValueError("stored scenario participants are invalid")
        people: dict[str, _Person] = {}
        for participant_id, raw_person in raw_people.items():
            if not isinstance(participant_id, str) or not isinstance(raw_person, dict):
                raise ValueError("stored scenario participant is invalid")
            roles = raw_person.get("roles")
            location_id = raw_person.get("location_id")
            if (
                not isinstance(roles, list)
                or not roles
                or any(not isinstance(role, str) for role in roles)
                or not isinstance(location_id, str)
                or location_id not in pack.location_by_id
            ):
                raise ValueError("stored scenario participant state is invalid")
            people[participant_id] = _Person(frozenset(roles), location_id)

        try:
            status = ScenarioStatus(_snapshot_string(snapshot, "status"))
        except ValueError as exc:
            raise ValueError("stored scenario status is invalid") from exc
        used_capabilities = _snapshot_string_list(snapshot.get("used_capabilities"))
        interventions = _snapshot_triplets(snapshot.get("interventions"))
        active_faults = _snapshot_pairs(snapshot.get("active_faults"))
        original_faults = {(item.component_id, item.mode) for item in fault.faults}
        if not set(active_faults).issubset(original_faults):
            raise ValueError("stored active faults do not match the original fault set")

        raw_presence_values = snapshot.get("presence_values")
        if raw_presence_values is None:
            presence_values: dict[str, str] = {}
        else:
            presence_values = _snapshot_presence_values(pack, raw_presence_values)
        presence_attempts = _snapshot_presence_attempts(
            snapshot.get("presence_attempts", []), people, presence_values, pack
        )

        scenario = cls(
            scenario_id,
            pack,
            fault,
            salt,
            commitment,
            people,
            status=status,
            presence_values=presence_values,
            presence_attempts=presence_attempts,
            documented_model=DocumentedModel.model_validate(snapshot["documented_model"])
            if "documented_model" in snapshot
            else None,
        )
        scenario.used_capabilities = set(used_capabilities)
        scenario.interventions = interventions
        scenario._active_faults = set(active_faults)
        scenario.world = World(pack, frozenset(scenario._active_faults))
        return scenario

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
            labels=[
                ViewLabel(token_id=t.id, label=t.label, value=self.presence_values[t.id])
                for t in self.pack.presence_tokens
                if t.at == person.location_id
            ],
        )

    def check_presence(
        self, participant_id: str, token_id: str, answer: str
    ) -> PresenceCheckResult:
        """Compare a reading of a presence token with its value, without disclosing it."""
        self._person(participant_id)
        if token_id not in self.presence_values:
            raise ScenarioError(422, "UNKNOWN_TOKEN", f"unknown presence token {token_id}")
        key = (participant_id, token_id)
        used = self.presence_attempts.get(key, 0)
        if used >= PRESENCE_ATTEMPTS:
            return PresenceCheckResult(passed=False, attempts_left=0)
        self.presence_attempts[key] = used + 1
        reading = canonical_reading(answer)
        passed = bool(reading) and secrets.compare_digest(reading, self.presence_values[token_id])
        return PresenceCheckResult(passed=passed, attempts_left=PRESENCE_ATTEMPTS - used - 1)

    def _can_enter(self, person: _Person, location_id: str) -> bool:
        loc = self.pack.location_by_id[location_id]
        return not loc.restricted or bool(person.roles & {str(r) for r in loc.access_roles})

    def _reachable(self, person: _Person) -> list[str]:
        if not person.roles & {str(r) for r in self.pack.walking_roles}:
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
            where = "here" if probe.is_device else f"at {person.location_id}"
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
        if not person.roles & {str(r) for r in action.roles}:
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


def _snapshot_string(snapshot: Mapping[str, Any], key: str) -> str:
    value = snapshot.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"stored scenario {key} is invalid")
    return value


def _snapshot_string_list(value: object) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError("stored scenario capabilities are invalid")
    return value


def _snapshot_pairs(value: object) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        raise ValueError("stored scenario faults are invalid")
    pairs: list[tuple[str, str]] = []
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) != 2
            or not all(isinstance(part, str) for part in item)
        ):
            raise ValueError("stored scenario fault is invalid")
        pairs.append((item[0], item[1]))
    return pairs


def _snapshot_triplets(value: object) -> list[tuple[str, str, str]]:
    if not isinstance(value, list):
        raise ValueError("stored scenario interventions are invalid")
    triplets: list[tuple[str, str, str]] = []
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) != 3
            or not all(isinstance(part, str) for part in item)
        ):
            raise ValueError("stored scenario intervention is invalid")
        triplets.append((item[0], item[1], item[2]))
    return triplets


def _snapshot_presence_values(pack: DomainPack, value: object) -> dict[str, str]:
    if not isinstance(value, dict) or any(
        not isinstance(token_id, str) or not isinstance(reading, str)
        for token_id, reading in value.items()
    ):
        raise ValueError("stored presence values are invalid")
    expected = {token.id for token in pack.presence_tokens}
    if set(value) != expected or any(
        len(reading) != PRESENCE_LENGTH or set(reading) - set(PRESENCE_ALPHABET)
        for reading in value.values()
    ):
        raise ValueError("stored presence values do not match the pack")
    return value


def _snapshot_presence_attempts(
    value: object,
    people: Mapping[str, _Person],
    presence_values: Mapping[str, str],
    pack: DomainPack,
) -> dict[tuple[str, str], int]:
    if not isinstance(value, list):
        raise ValueError("stored presence attempts are invalid")
    attempts: dict[tuple[str, str], int] = {}
    for item in value:
        if (
            not isinstance(item, list)
            or len(item) != 3
            or not isinstance(item[0], str)
            or not isinstance(item[1], str)
            or not isinstance(item[2], int)
            or isinstance(item[2], bool)
        ):
            raise ValueError("stored presence attempt is invalid")
        participant_id, token_id, count = item
        if (
            participant_id not in people
            or token_id not in presence_values
            or not 1 <= count <= PRESENCE_ATTEMPTS
            or (participant_id, token_id) in attempts
        ):
            raise ValueError("stored presence attempt state is invalid")
        attempts[(participant_id, token_id)] = count
    if not presence_values and pack.presence_tokens:
        return {}
    return attempts
