"""Render a planned probe into the participant's language from the pack's reviewed templates.

Templates are fixed text written for each probe, so a question never mentions hypotheses or
causes and never asks anyone to touch equipment. Only the place name is substituted.
"""

from __future__ import annotations

from pramana_contracts import ProbeAction, TemplateLanguage
from pramana_domain import DomainPack


def realize(pack: DomainPack, action: ProbeAction, language: TemplateLanguage) -> str:
    probe = pack.probe_by_id[action.probe_id]
    place = pack.location_by_id[action.location_id].label.get(language)
    text = probe.templates[language].replace("{place}", place)
    if action.requires_move:
        text = pack.move_templates[language].replace("{place}", place) + text
    return text
