"""Starter site descriptions shipped with Pramana, and the equipment library as plain data.

Templates are ordinary site descriptions (``builder.SiteDescription``) stored as JSON files in
``templates/``. A new organization copies one into a draft and edits it; nothing here is tied to
one building, and no template is required.
"""

from __future__ import annotations

import json
from functools import cache
from importlib import resources
from typing import Any

from .builder import SiteDescription
from .library import LIBRARY


@cache
def templates() -> dict[str, dict[str, Any]]:
    """Template id -> ``{id, title, kind, summary, description}``, validated once."""
    found: dict[str, dict[str, Any]] = {}
    for entry in sorted(resources.files(__package__).joinpath("templates").iterdir(), key=str):
        if not entry.name.endswith(".json"):
            continue
        doc = json.loads(entry.read_text(encoding="utf-8"))
        SiteDescription.model_validate(doc["description"])
        found[doc["id"]] = doc
    return found


def template(template_id: str) -> dict[str, Any] | None:
    doc = templates().get(template_id)
    return json.loads(json.dumps(doc["description"])) if doc else None  # a private copy


def equipment_types() -> list[dict[str, Any]]:
    """What a site author may choose from, with each type's faults, checks and repairs."""
    return [
        {
            "id": t.id,
            "label": t.label,
            "failure_modes": [
                {"id": f.id, "label": f.label, "prior": f.prior, "local": f.local}
                for f in t.failures
            ],
            "checks": [
                {"id": c.id, "label": c.label, "outcomes": list(c.outcomes), "skill": c.skill}
                for c in t.checks
            ],
            "repairs": [{"id": r.id, "label": r.label, "trade": r.trade} for r in t.repairs],
            "keywords": list(t.keywords),
        }
        for t in LIBRARY.values()
    ]
