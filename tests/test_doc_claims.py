"""Guard submission-facing claims and repository links in the judge path."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (Path("README.md"), Path("docs/SUBMISSION.md"), Path("docs/DEMO.md"))
LINK_DOCUMENTS = (
    *DOCUMENTS,
    Path("docs/COMPETITORS.md"),
    Path("docs/engineering/ARTIFACT_INDEX.md"),
    Path("docs/engineering/HANDOFF.md"),
    Path("docs/engineering/LANGUAGE_REVIEW.md"),
    Path("docs/engineering/VOICE_PROVENANCE.md"),
    Path("docs/engineering/STATUS_2026-11-10.md"),
)
SOURCE_HINT = re.compile(
    r"https?://|\bADR\s*\d+\b|summary\.json|report\.md|eval/reports/|"
    r"(?:docs|tests|packages|services|eval)/[\w./-]+",
    re.IGNORECASE,
)
LINK = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
SPEECH_METRIC = re.compile(
    r"\b(?:speech(?:[- ]recognition)?|recognition|transcription)\b.{0,60}"
    r"\b(?:accuracy|word error rate|error rate|wer|cer)\b.{0,30}"
    r"\b\d+(?:\.\d+)?\s*(?:%|percent\b)|"
    r"\b(?:accuracy|word error rate|error rate|wer|cer)\b.{0,30}"
    r"\b(?:speech|recognition|transcription)\b.{0,30}"
    r"\b\d+(?:\.\d+)?\s*(?:%|percent\b)",
    re.IGNORECASE,
)


def _claims(text: str) -> list[str]:
    findings: list[str] = []
    for paragraph in text.split("\n\n"):
        normalized = paragraph.casefold()
        if "frontier" in normalized and "llm" in normalized:
            claim = re.search(
                r"\b(?:outperform\w*|beat\w*|better than|superior to|more accurate than)\b",
                normalized,
            )
            negated = re.search(
                r"\b(?:no|not|never|without|cannot|can't|does not|do not|isn't|is not)\b"
                r"(?:\W+\w+){0,5}\W+"
                r"(?:outperform\w*|beat\w*|better than|superior to|more accurate than)\b",
                normalized,
            )
            if claim and not negated:
                findings.append("unqualified frontier LLM superiority claim")

        site = re.search(r"\b(?:real[- ]site|real building|field deployment)\b", normalized)
        result = re.search(
            r"\b(?:result\w*|performance|success|accuracy|validated|demonstrated|proven|works?)\b",
            normalized,
        )
        if site and result:
            site_context = normalized[max(0, site.start() - 100) : site.end() + 120]
            has_qualifier = bool(
                re.search(
                    r"\b(?:no|not|never|without|cannot|does not|do not|is not|are not|"
                    r"has not|have not|simulat\w*|hypothetical|planned)\b",
                    site_context,
                )
            )
            if not has_qualifier:
                findings.append("unqualified real-site result claim")

        if "significant" in normalized and not SOURCE_HINT.search(paragraph):
            findings.append("significance claim has no source in its paragraph")

    if SPEECH_METRIC.search(text):
        findings.append("speech accuracy or error-rate number")
    return findings


def _missing_links(root: Path, document: Path, text: str) -> list[str]:
    missing: list[str] = []
    for match in LINK.finditer(text):
        target = match.group(1).strip()
        if target.startswith("<") and ">" in target:
            target = target[1 : target.index(">")]
        else:
            target = target.split(maxsplit=1)[0]
        parsed = urlsplit(target)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        local = (root / document.parent / unquote(parsed.path)).resolve()
        if not local.exists():
            missing.append(parsed.path)
    return missing


def test_submission_judge_path_has_supported_claims_and_existing_local_links() -> None:
    for relative in DOCUMENTS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert _claims(text) == [], f"{relative}: {_claims(text)}"
    for relative in LINK_DOCUMENTS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        missing = _missing_links(ROOT, relative, text)
        assert missing == [], f"{relative}: {missing}"


@pytest.mark.parametrize(
    "text",
    [
        "Pramana outperforms frontier LLMs on diagnosis.",
        "The field deployment produced strong real-site results.",
        "Speech recognition accuracy reached 97%.",
        "There was a significant improvement.",
    ],
)
def test_unsupported_claim_fixtures_fail(text: str) -> None:
    assert _claims(text)


@pytest.mark.parametrize(
    "text",
    [
        "No frontier LLM comparison is claimed.",
        "The simulated result is not a real-site outcome.",
        "Speech accuracy is not measured or published.",
        "There was no significant change in success (ADR 0011).",
    ],
)
def test_scoped_or_sourced_claim_fixtures_pass(text: str) -> None:
    assert _claims(text) == []


def test_missing_repository_link_is_reported() -> None:
    assert _missing_links(ROOT, Path("docs/DEMO.md"), "[missing](../missing-report.md)") == [
        "../missing-report.md"
    ]
