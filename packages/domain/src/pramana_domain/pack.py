"""Domain pack schema, loader and cross-reference validation.

A pack is the *documented* model of a site: components and their dependencies, locations and
walking times, safe probes with question templates, decision classes and a loss matrix. Packs are
untrusted input; every reference is checked so a typo fails at load time with a readable message
instead of silently producing a wrong prediction table.
"""

from __future__ import annotations

import heapq
import os
from collections.abc import Iterable
from functools import cached_property
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator

from pramana_contracts import Role, TemplateLanguage

NO_FAULT = "NO_FAULT"
OPEN_WORLD = "OPEN_WORLD"
ANY_ROLE = "any"

ComponentKind = Literal[
    "feed",
    "breaker",
    "light",
    "nvr",
    "socket",
    "isp",
    "ont",
    "gateway",
    "dhcp",
    "dns",
    "switch",
    "ap",
]
ObservableKind = Literal[
    "internet_works",
    "wifi_status",
    "web_by_ip",
    "powered",
    "ap_light",
    "switch_leds",
    "wan_led",
    "fibre_led",
    "breaker",
]
ProbeClass = Literal["device", "visual", "panel"]

# Outcome vocabulary each observable kind can produce (physics.py implements the mapping).
KIND_OUTCOMES: dict[str, frozenset[str]] = {
    "internet_works": frozenset({"yes", "no"}),
    "wifi_status": frozenset({"no_network", "stuck_connecting", "connected"}),
    "web_by_ip": frozenset({"yes", "no"}),
    "powered": frozenset({"on", "off"}),
    "ap_light": frozenset({"on", "off"}),
    "switch_leds": frozenset({"green", "amber", "off"}),
    "wan_led": frozenset({"green", "red", "off"}),
    "fibre_led": frozenset({"green", "red", "off"}),
    "breaker": frozenset({"up", "tripped"}),
}
# Observable kinds that read a specific component (and the component kinds they accept).
TARGET_KINDS: dict[str, frozenset[str]] = {
    "powered": frozenset({"light", "nvr", "socket"}),
    "ap_light": frozenset({"ap"}),
    "switch_leds": frozenset({"switch"}),
    "wan_led": frozenset({"gateway"}),
    "fibre_led": frozenset({"ont"}),
    "breaker": frozenset({"breaker"}),
}
DEVICE_KINDS = frozenset({"internet_works", "wifi_status", "web_by_ip"})


class PackModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LocalizedText(PackModel):
    en: StrictStr
    hi: StrictStr
    mr: StrictStr
    hi_en: StrictStr | None = Field(default=None, alias="hi-en")
    """Latin-script Hinglish. Without it, Hinglish uses ``hi`` if that is Latin, else ``en``."""

    def get(self, lang: TemplateLanguage) -> str:
        if lang == "hi-en":
            if self.hi_en is not None:
                return self.hi_en
            return self.hi if self.hi.isascii() else self.en
        return str(getattr(self, lang))


class Location(PackModel):
    id: StrictStr
    floor: int
    kind: Literal["room", "corridor", "closet", "desk", "panel"]
    label: LocalizedText
    restricted: bool = False
    access_roles: list[Role] = Field(default_factory=list)
    wifi_coverage: list[StrictStr] = Field(default_factory=list)
    """Access points whose signal reaches this location, strongest first."""


class FailureMode(PackModel):
    id: StrictStr
    prior: float = Field(gt=0, lt=1)
    label: StrictStr


class Component(PackModel):
    id: StrictStr
    kind: ComponentKind
    label: StrictStr
    location: StrictStr | None = None
    powered_by: StrictStr | None = None
    poe_from: StrictStr | None = None
    uplink: StrictStr | None = None
    hosted_on: StrictStr | None = None
    upstream: StrictStr | None = None
    failure_modes: list[FailureMode] = Field(default_factory=list)


class ProbeBinding(PackModel):
    at: StrictStr
    target: StrictStr | None = None


class Probe(PackModel):
    id: StrictStr
    label: StrictStr
    kind: ObservableKind
    probe_class: ProbeClass = Field(alias="class")
    outcomes: list[StrictStr] = Field(min_length=2)
    roles: list[StrictStr] = Field(min_length=1)
    exec_s: float = Field(gt=0)
    observes: list[ProbeBinding] = Field(min_length=1)
    templates: dict[TemplateLanguage, StrictStr]

    @field_validator("templates")
    @classmethod
    def _all_languages(cls, v: dict[str, str]) -> dict[str, str]:
        missing = {"en", "hi", "mr", "hi-en"} - set(v)
        if missing:
            raise ValueError(f"templates missing languages: {sorted(missing)}")
        return v

    def binding_at(self, location_id: str) -> ProbeBinding | None:
        return next((b for b in self.observes if b.at == location_id), None)

    def allows(self, roles: Iterable[str]) -> bool:
        return ANY_ROLE in self.roles or bool(set(self.roles) & set(roles))


class Action(PackModel):
    """A consequential action: role-restricted, approval-gated, executed with a capability."""

    id: StrictStr
    label: StrictStr
    target_kind: ComponentKind
    fixes: StrictStr
    """The failure mode this action clears on its target."""
    roles: list[Role] = Field(min_length=1)
    at_target_location: bool = True
    risk: Literal["low", "medium", "high"]
    reversible: bool
    decision_classes: list[StrictStr] = Field(min_length=1)
    instructions: dict[TemplateLanguage, StrictStr]


class PresenceToken(PackModel):
    """A detail only someone standing at a restricted place can read (PRODUCT.md U8).

    Its value is not in the pack: each simulated scenario draws a fresh one and shows it only
    to people who are there, and only the simulator can check an answer against it."""

    id: StrictStr
    at: StrictStr
    label: StrictStr
    """What the detail is, as shown on the participant's card ("Label on the network switch")."""
    templates: dict[TemplateLanguage, StrictStr]
    """The challenge question. ``{place}`` is the place's name."""

    @field_validator("templates")
    @classmethod
    def _all_languages(cls, v: dict[str, str]) -> dict[str, str]:
        missing = {"en", "hi", "mr", "hi-en"} - set(v)
        if missing:
            raise ValueError(f"templates missing languages: {sorted(missing)}")
        return v


class DecisionClass(PackModel):
    id: StrictStr
    label: StrictStr
    hypotheses: list[StrictStr] = Field(min_length=1)


class LossMinutes(PackModel):
    wrong_default: float = Field(gt=0)
    wrong_by_decision: dict[str, float] = Field(default_factory=dict)
    any_under_open_world: float = Field(gt=0)


class DomainPack(PackModel):
    pack: StrictStr
    version: StrictStr
    title: StrictStr
    locations: list[Location]
    walks: list[tuple[StrictStr, StrictStr, int]]
    walking_roles: list[Role]
    components: list[Component]
    no_fault_prior: float = Field(gt=0, lt=1)
    open_world_prior: float = Field(gt=0, lt=1)
    probes: list[Probe]
    actions: list[Action] = Field(default_factory=list)
    move_templates: dict[TemplateLanguage, StrictStr]
    decision_classes: list[DecisionClass]
    loss_minutes: LossMinutes
    presence_tokens: list[PresenceToken] = Field(default_factory=list)

    # -- indices ---------------------------------------------------------------------------

    @cached_property
    def location_by_id(self) -> dict[str, Location]:
        return {loc.id: loc for loc in self.locations}

    @cached_property
    def component_by_id(self) -> dict[str, Component]:
        return {c.id: c for c in self.components}

    @cached_property
    def probe_by_id(self) -> dict[str, Probe]:
        return {p.id: p for p in self.probes}

    @cached_property
    def decision_of(self) -> dict[str, str]:
        """Hypothesis id -> decision class id."""
        return {h: d.id for d in self.decision_classes for h in d.hypotheses}

    def presence_token_at(self, location_id: str) -> PresenceToken | None:
        return next((t for t in self.presence_tokens if t.at == location_id), None)

    def fault_hypotheses(self) -> list[tuple[str, str, FailureMode]]:
        """(component id, failure mode id, mode) for every modelled single fault."""
        return [(c.id, m.id, m) for c in self.components for m in c.failure_modes]

    # -- walking ---------------------------------------------------------------------------

    @cached_property
    def _walk_graph(self) -> dict[str, list[tuple[str, int]]]:
        graph: dict[str, list[tuple[str, int]]] = {loc.id: [] for loc in self.locations}
        for a, b, s in self.walks:
            graph[a].append((b, s))
            graph[b].append((a, s))
        return graph

    def walk_seconds(self, src: str, dst: str) -> int | None:
        """Shortest walking time (Dijkstra) or None when unreachable."""
        if src == dst:
            return 0
        dist: dict[str, int] = {src: 0}
        heap: list[tuple[int, str]] = [(0, src)]
        while heap:
            d, node = heapq.heappop(heap)
            if node == dst:
                return d
            if d > dist.get(node, 1 << 30):
                continue
            for nxt, w in self._walk_graph[node]:
                nd = d + w
                if nd < dist.get(nxt, 1 << 30):
                    dist[nxt] = nd
                    heapq.heappush(heap, (nd, nxt))
        return None

    # -- validation ------------------------------------------------------------------------

    @model_validator(mode="after")
    def _cross_references(self) -> DomainPack:
        errors: list[str] = []
        locs = {loc.id for loc in self.locations}
        comps = {c.id: c for c in self.components}
        _unique("location", [loc.id for loc in self.locations], errors)
        _unique("component", [c.id for c in self.components], errors)
        _unique("probe", [p.id for p in self.probes], errors)
        _unique("decision class", [d.id for d in self.decision_classes], errors)

        for loc in self.locations:
            for ap in loc.wifi_coverage:
                if comps.get(ap) is None or comps[ap].kind != "ap":
                    errors.append(f"location {loc.id}: wifi_coverage {ap!r} is not an access point")
            if loc.restricted and not loc.access_roles:
                errors.append(f"location {loc.id}: restricted but no access_roles")
        _unique("presence token", [t.id for t in self.presence_tokens], errors)
        _unique("presence token place", [t.at for t in self.presence_tokens], errors)
        for t in self.presence_tokens:
            if t.at not in locs:
                errors.append(f"presence token {t.id}: unknown location {t.at!r}")
            elif not self.location_by_id[t.at].restricted:
                errors.append(f"presence token {t.id}: {t.at} is not restricted")
        for src, dst, secs in self.walks:
            if src not in locs or dst not in locs:
                errors.append(f"walk {src}-{dst}: unknown location")
            if secs <= 0:
                errors.append(f"walk {src}-{dst}: duration must be positive")

        expected_parent = {
            "breaker": "powered_by",
            "light": "powered_by",
            "nvr": "powered_by",
            "socket": "powered_by",
            "ont": "powered_by",
            "switch": "powered_by",
            "gateway": "powered_by",
            "ap": "poe_from",
            "dhcp": "hosted_on",
            "dns": "hosted_on",
        }
        for c in self.components:
            for field in ("powered_by", "poe_from", "uplink", "hosted_on", "upstream"):
                ref = getattr(c, field)
                if ref is not None and ref not in comps:
                    errors.append(f"component {c.id}: {field} {ref!r} does not exist")
            need = expected_parent.get(c.kind)
            if need and getattr(c, need) is None:
                errors.append(f"component {c.id} ({c.kind}) needs {need}")
            if c.poe_from and c.poe_from in comps and comps[c.poe_from].kind != "switch":
                errors.append(f"component {c.id}: poe_from must reference a switch")
            if c.location is not None and c.location not in locs:
                errors.append(f"component {c.id}: unknown location {c.location!r}")
            _unique(f"failure mode of {c.id}", [m.id for m in c.failure_modes], errors)
        if not errors:
            errors.extend(_cycles(comps))

        for p in self.probes:
            allowed = KIND_OUTCOMES[p.kind]
            if set(p.outcomes) != allowed:
                errors.append(f"probe {p.id}: outcomes {p.outcomes} must equal {sorted(allowed)}")
            for role in p.roles:
                if role != ANY_ROLE and role not in {r.value for r in Role}:
                    errors.append(f"probe {p.id}: unknown role {role!r}")
            _unique(f"binding of probe {p.id}", [b.at for b in p.observes], errors)
            for b in p.observes:
                if b.at not in locs:
                    errors.append(f"probe {p.id}: unknown location {b.at!r}")
                if p.kind in TARGET_KINDS:
                    target = comps.get(b.target or "")
                    if target is None or target.kind not in TARGET_KINDS[p.kind]:
                        errors.append(
                            f"probe {p.id}@{b.at}: target {b.target!r} invalid for {p.kind}"
                        )
                elif b.target is not None:
                    errors.append(f"probe {p.id}@{b.at}: {p.kind} takes no target")
                elif b.at in locs and not self.location_by_id[b.at].wifi_coverage:
                    errors.append(f"probe {p.id}@{b.at}: device probe at a location without Wi-Fi")
            for lang, text in p.templates.items():
                if p.kind in DEVICE_KINDS and "{place}" in text:
                    errors.append(f"probe {p.id}: device template {lang} must not name a place")

        hyp_ids = {f"{c}.{m}" for c, m, _ in self.fault_hypotheses()} | {NO_FAULT}
        mapped: list[str] = [h for d in self.decision_classes for h in d.hypotheses]
        _unique("hypothesis in decision classes", mapped, errors)
        for h in mapped:
            if h not in hyp_ids:
                errors.append(f"decision classes reference unknown hypothesis {h!r}")
        for h in sorted(hyp_ids - set(mapped)):
            errors.append(f"hypothesis {h} has no decision class")
        decision_ids = {d.id for d in self.decision_classes}
        _unique("action", [a.id for a in self.actions], errors)
        for act in self.actions:
            targets = [c for c in self.components if c.kind == act.target_kind]
            if not any(act.fixes in {m.id for m in c.failure_modes} for c in targets):
                errors.append(f"action {act.id}: no {act.target_kind} can fail as {act.fixes!r}")
            for d in act.decision_classes:
                if d not in decision_ids:
                    errors.append(f"action {act.id}: unknown decision class {d!r}")
        for d in self.loss_minutes.wrong_by_decision:
            if d not in decision_ids:
                errors.append(f"loss_minutes references unknown decision {d!r}")
        if errors:
            raise ValueError("invalid domain pack:\n  - " + "\n  - ".join(errors))
        return self


def _unique(what: str, ids: list[str], errors: list[str]) -> None:
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            errors.append(f"duplicate {what} id {i!r}")
        seen.add(i)


def _cycles(comps: dict[str, Component]) -> list[str]:
    """Dependency edges must form a DAG, otherwise propagation would not terminate."""
    errors: list[str] = []
    state: dict[str, int] = {}

    def visit(cid: str, path: list[str]) -> None:
        if state.get(cid) == 2:
            return
        if state.get(cid) == 1:
            errors.append("dependency cycle: " + " -> ".join([*path, cid]))
            return
        state[cid] = 1
        c = comps[cid]
        for ref in (c.powered_by, c.poe_from, c.uplink, c.hosted_on, c.upstream):
            if ref is not None:
                visit(ref, [*path, cid])
        state[cid] = 2

    for cid in comps:
        visit(cid, [])
    return errors


def default_packs_dir() -> Path:
    env = os.environ.get("PRAMANA_PACKS_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[4] / "packs"


def load_pack(path_or_id: str | Path, packs_dir: Path | None = None) -> DomainPack:
    """Load and validate a pack from a YAML path, or by id from the ``packs/`` directory."""
    path = Path(path_or_id)
    if not path.suffix:
        if not str(path_or_id).replace("_", "").isalnum():
            raise ValueError(f"invalid pack id {path_or_id!r}")
        path = (packs_dir or default_packs_dir()) / f"{path_or_id}.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return DomainPack.model_validate(raw)
