"""Linter for everything Pramana says to a person: question templates, place names, the walking
prefix, repair instructions and fixed phrases such as the consent line.

The rules, one per issue code:

- ``language``: every text exists in English, Hindi, Marathi and Hinglish.
- ``placeholder``: only the placeholders the realizer fills (``{place}``, and ``{target}`` in
  repair instructions); nothing is left in braces after rendering.
- ``empty``: no text or place name is blank.
- ``script``: Hindi and Marathi are spoken in Devanagari (Latin is allowed only inside quotes,
  where it is a name read off a screen); English and Hinglish contain no Devanagari.
- ``spoken_code``: after the speakable rewrite, no equipment code reaches speech synthesis raw
  ("IDF-2", "C2-7").
- ``length``: a question is at most ``MAX_WORDS`` words (``MAX_WORDS_WITH_MOVE`` with the
  "please walk to" prefix), so it can be followed by ear.
- ``unsafe``: a question never asks anyone to operate equipment (reset, unplug, restart...).
  Repair instructions are exempt: they are sent only after a human approval.
- ``cause``: a question never names a cause or a fault (it would lead the answer).
- ``options``: a question with more than two possible answers names all of them, or is a yes or
  no question about exactly one, so the extractor can read a bare "yes".

Every probe is rendered at every place it can be asked, with and without the walking prefix, so
the place names are linted inside real questions, not only on their own.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pramana_contracts import TemplateLanguage
from pramana_domain import DomainPack

from .extraction import POLAR, named_outcomes
from .speakable import RAW_CODE, speakable

LANGUAGES: tuple[TemplateLanguage, ...] = ("en", "hi", "mr", "hi-en")
MAX_WORDS = 25
MAX_WORDS_WITH_MOVE = 35

_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"|‘[^’]*’|“[^”]*”")

_UNSAFE: dict[TemplateLanguage, re.Pattern[str]] = {
    "en": re.compile(
        r"\b(reset|reboot|restart|unplug|replug|flip|press|push|pull|toggle|remove|"
        r"(turn|switch|power)\s+(it\s+)?(off|back)|open\s+the\s+(panel|board|rack|cover))\b",
        re.IGNORECASE,
    ),
    "hi-en": re.compile(
        r"\b(reset|reboot|restart|unplug|nikaal|nikal|dabaa|dabao|dabaiye|"
        r"band\s+kar|off\s+kar|on\s+off)\w*",
        re.IGNORECASE,
    ),
    "hi": re.compile(r"(रीसेट|रिसेट|रीस्टार्ट|दबाइए|दबाएँ|दबाओ|निकालिए|निकालें|बंद कीजिए|बंद करें|बंद करो)"),
    "mr": re.compile(r"(रीसेट|रिसेट|रीस्टार्ट|दाबा|काढा|बंद करा)"),
}

_CAUSE: dict[TemplateLanguage, re.Pattern[str]] = {
    "en": re.compile(r"\b(fault|faulty|fail\w*|broken|dead|outage|cause\w*|problem)\b", re.I),
    "hi-en": re.compile(r"\b(fault|kharab|kharaab|kharabi|fail\w*|dead|outage|problem)\b", re.I),
    "hi": re.compile(r"(खराब|ख़राब|ख़राबी|खराबी|फ़ॉल्ट|फॉल्ट|समस्या)"),
    "mr": re.compile(r"(खराब|बिघड|फॉल्ट|बिघाड|अडचण)"),
}


@dataclass(frozen=True)
class LintIssue:
    code: str
    where: str
    language: str
    message: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.where} ({self.language}): {self.message}"


def _words(text: str) -> int:
    return len(text.split())


def _check_languages(where: str, texts: Mapping[Any, str], out: list[LintIssue]) -> None:
    for lang in LANGUAGES:
        if lang not in texts:
            out.append(LintIssue("language", where, lang, "missing"))
        elif not texts[lang].strip():
            out.append(LintIssue("empty", where, lang, "blank text"))


def _check_placeholders(
    where: str, texts: Mapping[Any, str], allowed: set[str], out: list[LintIssue]
) -> None:
    for lang, text in texts.items():
        names = set(_PLACEHOLDER.findall(text))
        for bad in sorted(names - allowed):
            out.append(LintIssue("placeholder", where, lang, f"unknown placeholder {{{bad}}}"))
        if _PLACEHOLDER.sub("", text).count("{") or _PLACEHOLDER.sub("", text).count("}"):
            out.append(LintIssue("placeholder", where, lang, "unbalanced brace"))


def lint_spoken(where: str, language: TemplateLanguage, text: str) -> list[LintIssue]:
    """Rules for one finished text that will be shown and spoken."""
    out: list[LintIssue] = []
    if "{" in text or "}" in text:
        out.append(LintIssue("placeholder", where, language, f"unfilled placeholder in {text!r}"))
    speech = speakable(text, language)
    raw = RAW_CODE.search(speech)
    if raw:
        out.append(
            LintIssue("spoken_code", where, language, f"{raw.group(0)!r} spoken raw: {speech!r}")
        )
    unquoted = _QUOTED.sub(" ", speech)
    if language in ("hi", "mr"):
        latin = _LATIN_WORD.findall(unquoted)
        if latin:
            out.append(LintIssue("script", where, language, f"Latin words {latin} in {text!r}"))
    elif _DEVANAGARI.search(text):
        out.append(LintIssue("script", where, language, f"Devanagari in {text!r}"))
    return out


def _lint_question(
    where: str,
    language: TemplateLanguage,
    text: str,
    outcomes: list[str],
    max_words: int,
) -> list[LintIssue]:
    out = lint_spoken(where, language, text)
    n = _words(text)
    if n > max_words:
        out.append(LintIssue("length", where, language, f"{n} words (max {max_words})"))
    unsafe = _UNSAFE[language].search(text)
    if unsafe:
        out.append(LintIssue("unsafe", where, language, f"asks to operate: {unsafe.group(0)!r}"))
    cause = _CAUSE[language].search(text)
    if cause:
        out.append(LintIssue("cause", where, language, f"names a cause: {cause.group(0)!r}"))
    if set(outcomes) != {"yes", "no"}:
        named = named_outcomes(text, outcomes)
        polar = len(named) == 1 and tuple(sorted(outcomes)) in POLAR
        if named != set(outcomes) and not polar:
            missing = sorted(set(outcomes) - named)
            out.append(LintIssue("options", where, language, f"does not offer {missing}: {text!r}"))
    return out


def lint_pack(
    pack: DomainPack, extra: Mapping[str, Mapping[str, str]] | None = None
) -> list[LintIssue]:
    """Every issue in the pack's texts, plus ``extra`` fixed phrases (name -> language -> text)."""
    out: list[LintIssue] = []
    for loc in pack.locations:
        labels = {lang: loc.label.get(lang) for lang in LANGUAGES}
        _check_languages(f"place {loc.id}", labels, out)
    _check_languages("move prefix", pack.move_templates, out)
    _check_placeholders("move prefix", pack.move_templates, {"place"}, out)
    for act in pack.actions:
        where = f"action {act.id}"
        _check_languages(where, act.instructions, out)
        _check_placeholders(where, act.instructions, {"place", "target"}, out)
        for lang, text in act.instructions.items():
            loc = next((loc for loc in pack.locations if loc.restricted), pack.locations[0])
            rendered = text.replace("{place}", loc.label.get(lang)).replace("{target}", "C2-7")
            out += lint_spoken(where, lang, rendered)
    for probe in pack.probes:
        where = f"probe {probe.id}"
        _check_languages(where, probe.templates, out)
        _check_placeholders(where, probe.templates, {"place"}, out)
        for lang, template in probe.templates.items():
            for binding in probe.observes:
                place = pack.location_by_id[binding.at].label.get(lang)
                text = template.replace("{place}", place)
                at = f"{where} at {binding.at}"
                out += _lint_question(at, lang, text, probe.outcomes, MAX_WORDS)
                move = pack.move_templates.get(lang, "").replace("{place}", place)
                out += _lint_question(
                    f"{at} after walking", lang, move + text, probe.outcomes, MAX_WORDS_WITH_MOVE
                )
    for name, texts in (extra or {}).items():
        _check_languages(name, texts, out)
        _check_placeholders(name, texts, set(), out)
        for key, phrase in texts.items():
            if key in LANGUAGES:
                out += lint_spoken(name, key, phrase)
    return _dedupe(out)


def _dedupe(issues: Iterable[LintIssue]) -> list[LintIssue]:
    seen: set[LintIssue] = set()
    out = []
    for i in issues:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out
