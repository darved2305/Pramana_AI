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
BACKTICK_PATH = re.compile(
    r"`((?:docs|tests|packages|services|eval|scripts|apps|packs|infra|\.github)/[^`\s*<>{}]+)`"
)
FILL_FIELD = re.compile(r"\[Fill[^\]]*\]", re.DOTALL)
COMPARISON = re.compile(
    r"\b(?:outperform\w*|beat\w*|better than|superior to|more accurate than|exceeds?)\b"
)
MODEL_OR_FRONTIER = re.compile(
    r"\b(?:frontier|gpt\w*|claude|gemini|llama|mistral|chatgpt|openai|anthropic)\b"
)
NEGATION = re.compile(
    r"\b(?:no|not|never|without|cannot|can't|does not|do not|isn't|is not)\b"
    r"(?:\W+\w+){0,5}\W+"
    r"(?:outperform\w*|beat\w*|better than|superior to|more accurate than|exceeds?)\b"
)
SPEECH_METRIC = re.compile(
    r"\b(?:speech(?:[- ]recognition)?|recognition|transcription|stt|asr|prisma|timbre|gnani)\b"
    r".{0,60}\b(?:accuracy|word error rate|error rate|wer|cer)\b.{0,30}"
    r"\b\d+(?:\.\d+)?\s*(?:%|percent\b)|"
    r"\b(?:accuracy|word error rate|error rate|wer|cer)\b.{0,30}"
    r"\b(?:speech|recognition|transcription|stt|asr|prisma|timbre|gnani)\b"
    r".{0,30}\b\d+(?:\.\d+)?\s*(?:%|percent\b)|"
    r"\b(?:word error rate|wer|cer)\b.{0,30}\b\d+(?:\.\d+)?\s*(?:%|percent\b)",
    re.IGNORECASE,
)


def _claims(text: str) -> list[str]:
    findings: list[str] = []
    for paragraph in text.split("\n\n"):
        normalized = paragraph.casefold()
        if (
            MODEL_OR_FRONTIER.search(normalized)
            and COMPARISON.search(normalized)
            and not NEGATION.search(normalized)
        ):
            findings.append("unqualified comparison with a frontier or named LLM")

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


def _missing_backtick_paths(root: Path, text: str) -> list[str]:
    """Repository paths written in code spans must exist, except inside [Fill: ...] fields."""
    missing: list[str] = []
    unfilled = FILL_FIELD.sub("", text)
    for line in unfilled.splitlines():
        for match in BACKTICK_PATH.finditer(line):
            path = match.group(1).rstrip(".,;:)")
            if "*" in path or not (root / path).exists():
                missing.append(path)
    return missing


def test_submission_judge_path_has_supported_claims_and_existing_local_links() -> None:
    for relative in DOCUMENTS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert _claims(text) == [], f"{relative}: {_claims(text)}"
        missing_paths = _missing_backtick_paths(ROOT, text)
        assert missing_paths == [], f"{relative}: {missing_paths}"
    for relative in LINK_DOCUMENTS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        missing = _missing_links(ROOT, relative, text)
        assert missing == [], f"{relative}: {missing}"


def test_readme_and_docs_have_no_em_dashes() -> None:
    paths = [ROOT / "README.md", *(ROOT / "docs").rglob("*")]
    offenders = [
        str(path.relative_to(ROOT))
        for path in paths
        if path.is_file() and chr(0x2014) in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_judge_docs_avoid_internal_lane_labels() -> None:
    paths = [
        ROOT / "README.md",
        *(ROOT / "docs").glob("*.md"),
        ROOT / "docs/engineering/STATUS_2026-11-10.md",
    ]
    label = re.compile(r"\bB[0-9]L?\b|Day-?1|lane", re.IGNORECASE)
    for path in paths:
        assert not label.search(path.read_text(encoding="utf-8")), path


@pytest.mark.parametrize(
    "text",
    [
        "Pramana outperforms frontier LLMs on diagnosis.",
        "Pramana outperforms GPT-5 on fault diagnosis.",
        "Pramana beats Claude on investigation tasks.",
        "The field deployment produced strong real-site results.",
        "Speech recognition accuracy reached 97%.",
        "Prisma v3.0 accuracy is 96.5% on Hindi audio.",
        "Word error rate of 12 percent on Marathi audio.",
        "There was a significant improvement.",
    ],
)
def test_unsupported_claim_fixtures_fail(text: str) -> None:
    assert _claims(text)


@pytest.mark.parametrize(
    "text",
    [
        "No frontier LLM comparison is claimed.",
        "Pramana does not outperform frontier LLMs; no such comparison was run.",
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


def test_missing_backtick_repository_path_is_reported() -> None:
    text = "See `docs/does-not-exist.md` and `tests/test_doc_claims.py`."
    assert _missing_backtick_paths(ROOT, text) == ["docs/does-not-exist.md"]


def test_fill_placeholder_paths_are_not_checked() -> None:
    text = "- Report: [Fill: link to `eval/reports/m2-human/` when it exists.]"
    assert _missing_backtick_paths(ROOT, text) == []
