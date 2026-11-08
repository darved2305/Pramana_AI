"""Declarative observation rules for sites described as a dependency graph.

A site that is not a building network (cooling, water, lifts, medical gas, payment terminals,
servers, anything with parts that depend on other parts) is modelled as data:

* each component lists what it ``requires``: another component, or ``{any_of: [...]}`` for
  redundant supply (two pumps, two feeds). A component is *supplied* when every requirement
  is met by a component that is *alive*, and *alive* when it is supplied and has no active
  blocking fault;
* a failure mode marked ``local`` breaks only the component itself (a faulty sensor, a dead
  display): its dependents keep working, but rules can still see it through ``faulty`` and
  ``fault``;
* each probe maps the world to an outcome with ordered ``when`` rules and a ``default``.

Rules only read component state, so the engine (documented model) and the simulator (sealed
true faults) evaluate the same rules on different inputs, exactly as with the built-in physics.
``$target`` in a condition means the component the probe's binding points at, so one probe
("Is the unit in this room blowing cold air?") can be placed at many locations.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

TARGET = "$target"


class _RuleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Condition(_RuleModel):
    """Exactly one of the fields is set. Component references may be ``$target``."""

    alive: StrictStr | None = None
    """The component works: supplied and no blocking fault."""
    supplied: StrictStr | None = None
    """Everything the component requires is alive (whatever its own state)."""
    faulty: StrictStr | None = None
    """The component has any active fault, local or blocking."""
    fault: StrictStr | None = None
    """A specific fault ``COMPONENT.mode`` is active."""
    all: list[Condition] | None = Field(default=None, min_length=1)
    any: list[Condition] | None = Field(default=None, min_length=1)
    not_: Condition | None = Field(default=None, alias="not")

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    @model_validator(mode="after")
    def _exactly_one(self) -> Condition:
        set_fields = [
            name
            for name in ("alive", "supplied", "faulty", "fault", "all", "any", "not_")
            if getattr(self, name) is not None
        ]
        if len(set_fields) != 1:
            raise ValueError(
                "a condition needs exactly one of alive, supplied, faulty, fault, all, any, not"
            )
        if self.fault is not None and "." not in self.fault:
            raise ValueError(f"fault {self.fault!r} must be COMPONENT.mode")
        return self

    def references(self) -> Iterator[tuple[str, str]]:
        """(operator, reference) for every leaf, for cross-reference validation."""
        for op in ("alive", "supplied", "faulty", "fault"):
            ref = getattr(self, op)
            if ref is not None:
                yield op, ref
        for child in (self.all or []) + (self.any or []):
            yield from child.references()
        if self.not_ is not None:
            yield from self.not_.references()


class Rule(_RuleModel):
    when: Condition
    outcome: StrictStr


class Requirement(_RuleModel):
    """Redundant supply: alive when at least one member is alive."""

    any_of: list[StrictStr] = Field(min_length=1)


RequirementSpec = StrictStr | Requirement
PhysicsKind = Literal["building_network", "dependency"]


class StateOracle(Protocol):
    """What rules may read about one world. ``physics.World`` implements it."""

    def alive(self, cid: str) -> bool: ...
    def supplied(self, cid: str) -> bool: ...
    def faulty(self, cid: str) -> bool: ...
    def fault(self, cid: str, mode: str) -> bool: ...


def resolve(ref: str, target: str | None) -> str:
    if ref == TARGET or ref.startswith(TARGET + "."):
        if target is None:
            raise ValueError("$target used by a binding without a target")
        return target + ref[len(TARGET) :]
    return ref


def holds(cond: Condition, world: StateOracle, target: str | None) -> bool:
    if cond.alive is not None:
        return world.alive(resolve(cond.alive, target))
    if cond.supplied is not None:
        return world.supplied(resolve(cond.supplied, target))
    if cond.faulty is not None:
        return world.faulty(resolve(cond.faulty, target))
    if cond.fault is not None:
        cid, _, mode = resolve(cond.fault, target).rpartition(".")
        return world.fault(cid, mode)
    if cond.all is not None:
        return all(holds(c, world, target) for c in cond.all)
    if cond.any is not None:
        return any(holds(c, world, target) for c in cond.any)
    assert cond.not_ is not None
    return not holds(cond.not_, world, target)


def evaluate(rules: list[Rule], default: str, world: StateOracle, target: str | None) -> str:
    """The first rule whose condition holds decides the outcome."""
    for rule in rules:
        if holds(rule.when, world, target):
            return rule.outcome
    return default


Condition.model_rebuild()
