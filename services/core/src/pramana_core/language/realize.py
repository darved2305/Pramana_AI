"""Render a planned probe into the participant's language from the pack's reviewed templates.

Templates are fixed text written for each probe, so a question never mentions hypotheses or
causes and never asks anyone to touch equipment. Only the place name is substituted.
"""

from __future__ import annotations

from pramana_contracts import ProbeAction, TemplateLanguage
from pramana_domain import DomainPack

CONFIRM_PREFIX: dict[TemplateLanguage, str] = {
    "en": "Sorry, just to be sure, once more: ",
    "hi-en": "Ek baar pakka kar lete hain: ",
    "hi": "एक बार पक्का कर लेते हैं: ",
    "mr": "एकदा खात्री करून घेऊया: ",
}
"""Asked when a spoken answer alone would change the decision. The question is repeated in its
original, item-specific form (not "did you say off?"), so the confirmation is not leading."""


def realize_challenge(
    pack: DomainPack, token_id: str, location_id: str, language: TemplateLanguage
) -> str:
    """The presence-check question for ``token_id`` (docs/adr/0014)."""
    token = next(t for t in pack.presence_tokens if t.id == token_id)
    place = pack.location_by_id[location_id].label.get(language)
    return token.templates[language].replace("{place}", place)


def realize(pack: DomainPack, action: ProbeAction, language: TemplateLanguage) -> str:
    probe = pack.probe_by_id[action.probe_id]
    place = pack.location_by_id[action.location_id].label.get(language)
    text = probe.templates[language].replace("{place}", place)
    if action.requires_move:
        text = pack.move_templates[language].replace("{place}", place) + text
    return text
