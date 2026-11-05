"""Lint every rendered participant prompt before a domain pack ships."""

from __future__ import annotations

import re
import sys
import unicodedata
from collections.abc import Mapping
from string import Formatter

from pramana_contracts import TemplateLanguage
from pramana_domain import DomainPack, load_pack
from pramana_domain.pack import default_packs_dir

from .realize import CONFIRM_PREFIX
from .speakable import speakable
from .speech_templates import CONSENT_TEXT

LANGUAGES: tuple[TemplateLanguage, ...] = ("en", "hi", "mr", "hi-en")
MAX_QUESTION_CHARACTERS = 260
MAX_QUESTION_WORDS = 50
MAX_OTHER_CHARACTERS = 360
MAX_OTHER_WORDS = 60

_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
_SNAKE_ID = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
_SEPARATED_ID = re.compile(r"\b[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+\b")

# Canonical pack outcomes with the short wording already used by the four prompt registers.
_OUTCOME_WORDING: dict[TemplateLanguage, dict[str, tuple[str, ...]]] = {
    "en": {
        "yes": ("yes",),
        "no": ("no",),
        "on": ("on", "come on"),
        "off": ("off",),
        "green": ("green",),
        "amber": ("amber", "orange"),
        "red": ("red",),
        "up": ("up",),
        "tripped": ("tripped", "down"),
        "no_network": ("missing", "not there", "not showing"),
        "stuck_connecting": ("stuck on connecting", "stuck", "connecting"),
        "connected": ("connected",),
    },
    "hi": {
        "yes": ("हाँ", "हां"),
        "no": ("नहीं", "नही"),
        "on": ("चालू", "जल रही", "जल रहा"),
        "off": ("बंद",),
        "green": ("हरी", "हरा", "हरे"),
        "amber": ("नारंगी", "नारिंगी"),
        "red": ("लाल",),
        "up": ("ऊपर",),
        "tripped": ("ट्रिप", "नीचे"),
        "no_network": ("दिख ही नहीं", "नहीं दिख"),
        "stuck_connecting": ("अटका", "अटकी", "अटके", "कनेक्ट होने पर अटका"),
        "connected": ("कनेक्टेड", "जुड़ गया", "जुड़ी"),
    },
    "mr": {
        "yes": ("हो", "होय"),
        "no": ("नाही",),
        "on": ("चालू", "लागतो", "लागते"),
        "off": ("बंद",),
        "green": ("हिरवा", "हिरवे", "हिरवी"),
        "amber": ("नारंगी", "नारिंगी"),
        "red": ("लाल",),
        "up": ("वर",),
        "tripped": ("ट्रिप", "खाली"),
        "no_network": ("दिसतच नाही", "दिसत नाही"),
        "stuck_connecting": ("अडकलं", "अडकले", "कनेक्ट होताना अडकलं"),
        "connected": ("कनेक्टेड", "जुडलं", "कनेक्ट झालं"),
    },
    "hi-en": {
        "yes": ("haan", "yes"),
        "no": ("nahi", "nahin", "no"),
        "on": ("on", "jal rahi", "chalu"),
        "off": ("off", "band"),
        "green": ("green",),
        "amber": ("amber", "orange"),
        "red": ("red",),
        "up": ("upar", "up"),
        "tripped": ("trip", "neeche", "niche"),
        "no_network": ("dikh hi nahi", "missing", "not showing"),
        "stuck_connecting": ("atka", "connecting pe atka", "stuck"),
        "connected": ("connected",),
    },
}

_OUTCOME_WORDING["en"]["on"] += ("charging", "start charging")
_OUTCOME_WORDING["hi"]["on"] += (
    "चार्ज",
    "चार्ज होने लगता",
)
_OUTCOME_WORDING["mr"]["on"] += (
    "चार्ज",
    "चार्ज व्हायला लागतो",
)
_OUTCOME_WORDING["hi-en"]["on"] += ("charge", "charging", "charge hone lagta")
_OUTCOME_WORDING["mr"]["stuck_connecting"] += ("\u0905\u0921\u0915\u0932\u0902\u092f",)


def _contains_phrase(text: str, phrase: str) -> bool:
    words = re.escape(phrase).replace(r"\ ", r"\s+")
    if any("\u0900" <= char <= "\u097f" for char in phrase):
        return re.search(words, text, re.IGNORECASE) is not None
    return re.search(rf"(?<!\w){words}(?!\w)", text, re.IGNORECASE) is not None


def _script_counts(text: str) -> tuple[int, int]:
    latin = devanagari = 0
    for char in text:
        category = unicodedata.category(char)
        if not (char.isalpha() or category.startswith("M")):
            continue
        name = unicodedata.name(char, "")
        if "LATIN" in name:
            latin += 1
        elif "DEVANAGARI" in name:
            devanagari += 1
    return latin, devanagari


def _render(
    template: str,
    values: Mapping[str, str],
    known_placeholders: frozenset[str],
    label: str,
    issues: list[str],
) -> str:
    try:
        parts = list(Formatter().parse(template))
    except ValueError as exc:
        issues.append(f"{label}: invalid placeholder syntax ({exc})")
        return template

    for _, field_name, format_spec, conversion in parts:
        if field_name is None:
            continue
        if field_name not in known_placeholders:
            issues.append(f"{label}: unknown placeholder '{{{field_name}}}'")
        elif field_name not in values:
            issues.append(f"{label}: placeholder '{{{field_name}}}' has no value")
        elif format_spec or conversion:
            issues.append(f"{label}: placeholder '{{{field_name}}}' cannot use formatting")

    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    if "{" in rendered or "}" in rendered:
        issues.append(f"{label}: stray braces remain after rendering")
    return rendered


def _lint_text(
    text: str,
    *,
    label: str,
    language: TemplateLanguage,
    issues: list[str],
    machine_ids: set[str],
    question: bool = False,
    fragment: bool = False,
    check_script: bool = True,
) -> str:
    if not text.strip() or text != text.strip():
        issues.append(f"{label}: template is empty or has outer whitespace")
    if "\u2014" in text:
        issues.append(f"{label}: em dash is not allowed")

    spoken = speakable(text, language)
    if check_script:
        for candidate in (text, spoken):
            latin, devanagari = _script_counts(candidate)
            letters = latin + devanagari
            if not letters:
                issues.append(f"{label}: text has no Latin or Devanagari letters")
            elif language in ("hi", "mr") and devanagari / letters < 0.55:
                issues.append(f"{label}: text must be mostly Devanagari")
            elif language in ("en", "hi-en") and latin / letters < 0.55:
                issues.append(f"{label}: text must be mostly Latin")

    for machine_id in sorted(machine_ids):
        if re.search(rf"(?<!\w){re.escape(machine_id)}(?!\w)", spoken, re.IGNORECASE):
            issues.append(f"{label}: raw machine ID {machine_id!r} remains after normalization")
    if _SNAKE_ID.search(spoken) or _SEPARATED_ID.search(spoken):
        issues.append(f"{label}: raw machine ID remains after normalization")

    if question:
        if "?" not in text and "？" not in text and text.rstrip()[-1:] not in ("।", "॥"):
            issues.append(f"{label}: question needs a question mark or language sentence ending")
        if len(spoken) > MAX_QUESTION_CHARACTERS:
            issues.append(
                f"{label}: exceeds the {MAX_QUESTION_CHARACTERS}-character question limit"
            )
        if len(spoken.split()) > MAX_QUESTION_WORDS:
            issues.append(f"{label}: exceeds the {MAX_QUESTION_WORDS}-word question limit")
    elif not fragment and text.rstrip()[-1:] not in (".", "?", "!", "।", "॥"):
        issues.append(f"{label}: sentence must end with sentence punctuation")
    if not question and len(spoken) > MAX_OTHER_CHARACTERS:
        issues.append(f"{label}: exceeds the {MAX_OTHER_CHARACTERS}-character prompt limit")
    if not question and len(spoken.split()) > MAX_OTHER_WORDS:
        issues.append(f"{label}: exceeds the {MAX_OTHER_WORDS}-word prompt limit")
    return spoken


def _lint_catalog(
    templates: Mapping[TemplateLanguage, str],
    *,
    name: str,
    placeholders: frozenset[str],
    locations: Mapping[str, Mapping[TemplateLanguage, str]],
    issues: list[str],
    machine_ids: set[str],
    fragment: bool = False,
    check_script: bool = True,
) -> None:
    for language in LANGUAGES:
        template = templates.get(language)
        if template is None:
            issues.append(f"{name} [${language}]: missing template language")
            continue
        for location, localized_places in locations.items():
            label = f"{name}@{location} [{language}]"
            if not check_script:
                without_slots = _PLACEHOLDER.sub("", template).strip()
                _lint_text(
                    without_slots,
                    label=label,
                    language=language,
                    issues=issues,
                    machine_ids=machine_ids,
                    fragment=True,
                )
            place = localized_places.get(language, "")
            rendered = _render(template, {"place": place}, placeholders, label, issues)
            _lint_text(
                rendered,
                label=label,
                language=language,
                issues=issues,
                machine_ids=machine_ids,
                fragment=fragment,
                check_script=check_script,
            )


def lint_pack(pack: DomainPack) -> list[str]:
    """Return clear, location-specific template issues for a loaded domain pack."""
    issues: list[str] = []
    all_ids = {probe.id for probe in pack.probes}
    all_ids.update(component.id for component in pack.components)
    all_ids.update(location.id for location in pack.locations)
    all_ids.update(action.id for action in pack.actions)
    all_ids.update(decision.id for decision in pack.decision_classes)
    all_ids.update(mode.id for component in pack.components for mode in component.failure_modes)
    machine_ids = {
        identifier for identifier in all_ids if any(char in identifier for char in "0123456789_-")
    }
    all_locations = {
        location.id: {language: location.label.get(language) for language in LANGUAGES}
        for location in pack.locations
    }
    empty_place = {language: "" for language in LANGUAGES}

    _lint_catalog(
        pack.move_templates,
        name="move_templates",
        placeholders=frozenset({"place"}),
        locations=all_locations,
        issues=issues,
        machine_ids=machine_ids,
        fragment=True,
        check_script=False,
    )
    _lint_catalog(
        CONFIRM_PREFIX,
        name="confirm_prefix",
        placeholders=frozenset(),
        locations={"*": empty_place},
        issues=issues,
        machine_ids=machine_ids,
        fragment=True,
    )
    _lint_catalog(
        CONSENT_TEXT,
        name="consent",
        placeholders=frozenset(),
        locations={"*": empty_place},
        issues=issues,
        machine_ids=machine_ids,
    )

    for probe in pack.probes:
        for binding in probe.observes:
            location = pack.location_by_id[binding.at]
            for language in LANGUAGES:
                label = f"{probe.id}@{binding.at} [{language}]"
                template = probe.templates.get(language)
                if template is None:
                    issues.append(f"{label}: missing template language")
                    continue
                values = {"place": location.label.get(language)}
                rendered = _render(template, values, frozenset({"place"}), label, issues)
                spoken = _lint_text(
                    rendered,
                    label=label,
                    language=language,
                    issues=issues,
                    machine_ids=machine_ids,
                    question=True,
                )
                covered_outcomes = {
                    outcome
                    for outcome in probe.outcomes
                    if any(
                        _contains_phrase(spoken, term)
                        for term in _OUTCOME_WORDING[language].get(outcome, ())
                    )
                }
                binary_polar = (
                    set(probe.outcomes) in ({"yes", "no"}, {"on", "off"})
                    and len(covered_outcomes) == 1
                )
                for outcome in probe.outcomes:
                    terms = _OUTCOME_WORDING[language].get(outcome, ())
                    if not binary_polar and not any(
                        _contains_phrase(spoken, term) for term in terms
                    ):
                        issues.append(
                            f"{label}: question does not offer answer outcome {outcome!r}"
                        )

                move_template = pack.move_templates.get(language, "")
                move_label = f"{probe.id}@{binding.at} [move, {language}]"
                prefix = _render(
                    move_template,
                    values,
                    frozenset({"place"}),
                    move_label,
                    issues,
                )
                moved = f"{prefix.rstrip()} {rendered}".strip()
                _lint_text(
                    moved,
                    label=move_label,
                    language=language,
                    issues=issues,
                    machine_ids=machine_ids,
                    question=True,
                )
                confirm = CONFIRM_PREFIX.get(language, "")
                for confirmation_label, question_text in (
                    ("confirmation", rendered),
                    ("move confirmation", moved),
                ):
                    confirmed = f"{confirm} {question_text}".strip()
                    _lint_text(
                        confirmed,
                        label=f"{probe.id}@{binding.at} [{confirmation_label}, {language}]",
                        language=language,
                        issues=issues,
                        machine_ids=machine_ids,
                        question=True,
                    )

    return issues


def main() -> int:
    """Lint every YAML pack in the repository. Usable as ``python -m ...realizer_lint``."""
    paths = sorted(default_packs_dir().glob("*.yaml"))
    if not paths:
        print(f"No YAML packs found in {default_packs_dir()}", file=sys.stderr)
        return 1
    failed = False
    for path in paths:
        pack = load_pack(path)
        issues = lint_pack(pack)
        if issues:
            failed = True
            for issue in issues:
                print(f"{path.name}: {issue}")
        else:
            print(f"{path.name}: passed")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
