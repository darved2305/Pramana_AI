"""Build an investigation model from a plain site description.

A site description is what a facilities manager already knows, in the shape asset registers
use: places, the roles of the people there, the equipment (each with a type from
``library.LIBRARY``, a location and what it depends on) and the **service points** where
people notice a problem (a tap, a light, the Wi-Fi in a room, a till that will not take
payments). Everything else the engine needs is generated:

* failure modes, checks and repairs from each equipment type;
* question wording in every language, with the equipment's name filled in;
* who may make each check, from the role catalogue's skills and each place's access list;
* one decision per fault, so a repair is never approved before its target is known;
* walking times between places when the author gives none.

The result is an ordinary ``DomainPack``: it is validated, then judged by the model health
check before anyone publishes it. Nothing here is specific to one kind of building.
"""

from __future__ import annotations

import itertools
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

from .library import LIBRARY, CheckSpec, EquipmentType, RepairSpec
from .pack import NO_FAULT, DomainPack, RoleDef, Slug
from .rules import Requirement

LANGS = ("en", "hi", "mr", "hi-en")
SKILL_RANK = {"lay": 0, "access": 1, "technician": 2}
DEFAULT_FLOOR_WALK_S = 20
DEFAULT_STAIRS_S = 45


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


Name = StrictStr | dict[Literal["en", "hi", "mr", "hi-en"], StrictStr]
"""One name for every language, or a name per language (English required)."""


class PlaceSpec(_Model):
    id: StrictStr = Field(pattern=r"^[A-Z][A-Z0-9_]{0,47}$")
    name: Name
    floor: int = 0
    kind: Slug = "room"
    restricted: bool = False
    access: list[Slug] = Field(default_factory=list)
    """Roles that may enter a restricted place."""


class EquipmentSpec(_Model):
    id: StrictStr = Field(pattern=r"^[A-Z][A-Z0-9_]{0,47}$")
    type: StrictStr
    name: Name
    at: StrictStr
    needs: list[StrictStr | Requirement] = Field(default_factory=list)
    """Equipment this one depends on; ``{any_of: [...]}`` for redundant supply."""
    priors: dict[StrictStr, float] = Field(default_factory=dict)
    """Override a failure mode's prior probability, e.g. ``{failed: 0.01}``."""


class ServicePoint(_Model):
    """What people notice: the equipment serving each place is working or not."""

    id: Slug
    label: StrictStr
    question: dict[Literal["en", "hi", "mr", "hi-en"], StrictStr]
    """Asked of someone at the place; may use ``{place}``."""
    outcomes: tuple[Slug, Slug]
    """(when the serving equipment works, when it does not), e.g. ``[flowing, dry]``."""
    served_by: dict[StrictStr, StrictStr] = Field(min_length=1)
    """Place id -> the equipment whose state people see there."""
    exec_s: int = Field(default=15, gt=0)


class SiteDescription(_Model):
    id: Slug
    title: StrictStr
    version: StrictStr = "0.1.0"
    roles: list[RoleDef] = Field(min_length=1)
    places: list[PlaceSpec] = Field(min_length=1)
    walks: list[tuple[StrictStr, StrictStr, int]] | None = None
    """Walking seconds between places. Omitted: generated from floors."""
    equipment: list[EquipmentSpec] = Field(min_length=1)
    service_points: list[ServicePoint] = Field(min_length=1)
    no_fault_prior: float = Field(default=0.003, gt=0, lt=1)
    open_world_prior: float = Field(default=0.0008, gt=0, lt=1)

    @model_validator(mode="after")
    def _references(self) -> SiteDescription:
        errors: list[str] = []
        places = {p.id for p in self.places}
        roles = {r.id for r in self.roles}
        equipment = {e.id: e for e in self.equipment}
        for p in self.places:
            for r in p.access:
                if r not in roles:
                    errors.append(f"place {p.id}: unknown role {r!r}")
            if p.restricted and not p.access:
                errors.append(f"place {p.id} is restricted: say which roles may enter")
        for e in self.equipment:
            if e.type not in LIBRARY:
                errors.append(f"{e.id}: unknown equipment type {e.type!r}")
                continue
            if e.at not in places:
                errors.append(f"{e.id}: unknown place {e.at!r}")
            for need in e.needs:
                for ref in need.any_of if isinstance(need, Requirement) else [need]:
                    if ref not in equipment:
                        errors.append(f"{e.id} needs {ref!r}, which is not listed")
            modes = {f.id for f in LIBRARY[e.type].failures}
            for mode in e.priors:
                if mode not in modes:
                    errors.append(f"{e.id}: a {e.type} cannot fail as {mode!r}")
        for sp in self.service_points:
            for place, eq in sp.served_by.items():
                if place not in places:
                    errors.append(f"service point {sp.id}: unknown place {place!r}")
                if eq not in equipment:
                    errors.append(f"service point {sp.id}: unknown equipment {eq!r}")
            missing = set(LANGS) - set(sp.question)
            if missing:
                errors.append(f"service point {sp.id}: question missing {sorted(missing)}")
        if errors:
            raise ValueError("invalid site description:\n  - " + "\n  - ".join(errors))
        return self


class BuildResult(_Model):
    spec: dict[str, Any]
    """The generated model in the stored format; hash it with ``spec_storage``."""
    notes: list[str]
    """What the builder could not generate and why (a check nobody may make)."""

    @property
    def pack(self) -> DomainPack:
        return DomainPack.model_validate(self.spec)


def _names(name: Name) -> dict[str, str]:
    if isinstance(name, str):
        return dict.fromkeys(LANGS, name)
    if "en" not in name:
        raise ValueError("a name per language needs English")
    return {lang: name.get(lang) or name["en"] for lang in LANGS}  # type: ignore[call-overload]


def _walks(desc: SiteDescription) -> list[list[Any]]:
    if desc.walks is not None:
        return [list(w) for w in desc.walks]
    by_floor: dict[int, list[PlaceSpec]] = {}
    for p in desc.places:
        by_floor.setdefault(p.floor, []).append(p)
    walks: list[list[Any]] = []
    hubs: list[str] = []
    for floor in sorted(by_floor):
        places = by_floor[floor]
        hub = next((p for p in places if not p.restricted), places[0])
        hubs.append(hub.id)
        walks.extend([hub.id, p.id, DEFAULT_FLOOR_WALK_S] for p in places if p.id != hub.id)
    walks.extend([a, b, DEFAULT_STAIRS_S] for a, b in itertools.pairwise(hubs))
    return walks


def _check_roles(desc: SiteDescription, check: CheckSpec, place: PlaceSpec) -> list[str]:
    need = SKILL_RANK[check.skill]
    return [
        r.id
        for r in desc.roles
        if SKILL_RANK[r.skill] >= need and (not place.restricted or r.id in place.access)
    ]


def _rules(check: CheckSpec) -> tuple[list[dict[str, Any]], str]:
    ok, bad = check.outcomes
    if check.rule == "alive":
        return [{"when": {"alive": "$target"}, "outcome": ok}], bad
    if check.rule == "not_tripped":
        return [{"when": {"fault": "$target.tripped"}, "outcome": bad}], ok
    if check.rule == "not_closed":
        return [{"when": {"fault": "$target.closed"}, "outcome": bad}], ok
    return [
        {"when": {"faulty": "$target"}, "outcome": bad},
        {"when": {"supplied": "$target"}, "outcome": ok},
    ], bad


def _repair_roles(desc: SiteDescription, repair: RepairSpec) -> list[str]:
    trade = [r.id for r in desc.roles if r.id == repair.trade]
    return trade or [r.id for r in desc.roles if r.skill == "technician"]


def build(desc: SiteDescription) -> BuildResult:
    notes: list[str] = []
    places = {p.id: p for p in desc.places}
    equipment_names = {e.id: _names(e.name) for e in desc.equipment}

    locations = [
        {
            "id": p.id,
            "floor": p.floor,
            "kind": p.kind,
            "label": _names(p.name),
            **({"restricted": True, "access_roles": list(p.access)} if p.restricted else {}),
        }
        for p in desc.places
    ]

    components: list[dict[str, Any]] = []
    for e in desc.equipment:
        etype = LIBRARY[e.type]
        components.append(
            {
                "id": e.id,
                "kind": e.type,
                "label": equipment_names[e.id]["en"],
                "location": e.at,
                "requires": [
                    {"any_of": list(n.any_of)} if isinstance(n, Requirement) else n for n in e.needs
                ],
                "failure_modes": [
                    {
                        "id": f.id,
                        "prior": e.priors.get(f.id, f.prior),
                        "label": f.label.format(name=equipment_names[e.id]["en"]),
                        **({"local": True} if f.local else {}),
                    }
                    for f in etype.failures
                ],
            }
        )

    probes: list[dict[str, Any]] = []
    for sp in desc.service_points:
        probes.append(
            {
                "id": sp.id,
                "label": sp.label,
                "kind": "rule",
                "class": "visual",
                "outcomes": list(sp.outcomes),
                "rules": [{"when": {"alive": "$target"}, "outcome": sp.outcomes[0]}],
                "default": sp.outcomes[1],
                "roles": ["any"],
                "exec_s": sp.exec_s,
                "observes": [{"at": at, "target": eq} for at, eq in sp.served_by.items()],
                "templates": dict(sp.question),
            }
        )
    for e in desc.equipment:
        etype = LIBRARY[e.type]
        for check in etype.checks:
            if check.rule == "not_tripped" and "tripped" not in {f.id for f in etype.failures}:
                continue
            roles = _check_roles(desc, check, places[e.at])
            name = equipment_names[e.id]
            label = check.label.format(name=name["en"])
            if not roles:
                notes.append(
                    f"Nobody may check '{label}': it needs a {check.skill} role allowed into "
                    f"{name['en']}'s place."
                )
                continue
            rules, default = _rules(check)
            probes.append(
                {
                    "id": f"{e.id.lower()}_{check.id}",
                    "label": label,
                    "kind": "rule",
                    "class": check.probe_class,
                    "outcomes": list(check.outcomes),
                    "rules": rules,
                    "default": default,
                    "roles": roles,
                    "exec_s": check.exec_s,
                    "observes": [{"at": e.at, "target": e.id}],
                    "templates": {
                        lang: text.replace("{name}", name[lang])
                        for lang, text in check.question.items()
                    },
                }
            )

    actions: list[dict[str, Any]] = []
    decision_classes: list[dict[str, Any]] = []
    loss_by_decision: dict[str, float] = {}
    used_types = {e.type: LIBRARY[e.type] for e in desc.equipment}
    repair_of: dict[tuple[str, str], tuple[EquipmentType, RepairSpec]] = {}
    for etype in used_types.values():
        for repair in etype.repairs:
            if repair.fixes not in {f.id for f in etype.failures}:
                continue
            roles = _repair_roles(desc, repair)
            if not roles:
                notes.append(f"Nobody may '{repair.label.lower()}': add a technician role.")
                continue
            repair_of[(etype.id, repair.fixes)] = (etype, repair)
    role_label = {r.id: r.label for r in desc.roles}
    action_decisions: dict[str, list[str]] = {}
    for e in desc.equipment:
        etype = LIBRARY[e.type]
        display = equipment_names[e.id]["en"]
        for f in etype.failures:
            decision = f"{e.id}_{f.id}".upper()
            fix = repair_of.get((etype.id, f.id))
            if fix is not None:
                repair = fix[1]
                who = role_label.get(repair.trade, "technician").lower()
                label = f"Send the {who} to {repair.verb} {display}"
                action_decisions.setdefault(f"{repair.id}_{etype.id}", []).append(decision)
            else:
                label = etype.escalation.format(name=display)
                loss_by_decision[decision] = 45.0
            decision_classes.append(
                {"id": decision, "label": label, "hypotheses": [f"{e.id}.{f.id}"]}
            )
    for (type_id, _), (_, repair) in repair_of.items():
        aid = f"{repair.id}_{type_id}"
        if aid not in action_decisions:
            continue
        actions.append(
            {
                "id": aid,
                "label": repair.label,
                "target_kind": type_id,
                "fixes": repair.fixes,
                "roles": _repair_roles(desc, repair),
                "at_target_location": True,
                "risk": repair.risk,
                "reversible": repair.reversible,
                "decision_classes": action_decisions[aid],
                "instructions": dict(repair.instructions),
            }
        )
    decision_classes.append(
        {
            "id": "CHECK_WITH_REPORTER",
            "label": "No equipment fault: help the reporter with what is in front of them",
            "hypotheses": [NO_FAULT],
        }
    )
    loss_by_decision["CHECK_WITH_REPORTER"] = 45.0

    spec: dict[str, Any] = {
        "pack": desc.id,
        "version": desc.version,
        "title": desc.title,
        "physics": "dependency",
        "roles": [r.model_dump(mode="json") for r in desc.roles],
        "locations": locations,
        "walks": _walks(desc),
        "walking_roles": [r.id for r in desc.roles if r.skill != "lay"],
        "components": components,
        "no_fault_prior": desc.no_fault_prior,
        "open_world_prior": desc.open_world_prior,
        "probes": probes,
        "actions": actions,
        "move_templates": {
            "en": "Could you please walk to {place}? Once you are there: ",
            "hi-en": "Kya aap {place} tak ja sakte hain? Wahan pahunch kar: ",
            "hi": "क्या आप {place} तक जा सकते हैं? वहाँ पहुँचकर: ",
            "mr": "तुम्ही {place} पर्यंत जाऊ शकाल का? तिथे पोहोचल्यावर: ",
        },
        "decision_classes": decision_classes,
        "loss_minutes": {
            "wrong_default": 30,
            "wrong_by_decision": loss_by_decision,
            "any_under_open_world": 30,
        },
    }
    DomainPack.model_validate(spec)  # raises with every problem listed
    return BuildResult(spec=spec, notes=notes)
