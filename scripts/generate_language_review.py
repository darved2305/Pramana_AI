"""Generate an unchecked review packet for user-visible Hindi, Marathi, and Hinglish copy."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pramana_contracts import ProbeAction, TemplateLanguage
from pramana_core.language.realize import CONFIRM_PREFIX, realize, realize_challenge
from pramana_core.language.speakable import speakable
from pramana_domain import load_pack

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "engineering" / "LANGUAGE_REVIEW.md"
LANGUAGES: tuple[TemplateLanguage, ...] = ("hi", "mr", "hi-en")
LANGUAGE_NAMES = {"hi": "Hindi", "mr": "Marathi", "hi-en": "Hinglish"}
LANGUAGE_KEYS = frozenset(LANGUAGE_NAMES)
DEVANAGARI = re.compile(r"[\u0900-\u097f]")
JS_LANGUAGE_KEY = re.compile(r"(?P<key>\"hi-en\"|'hi-en'|hi-en|\"hi\"|'hi'|hi|\"mr\"|'mr'|mr)\s*:")
JS_STRINGS = re.compile(r"\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`")

CODE_FILES = (
    Path("apps/web/src/components/landing/Hero.tsx"),
    Path("apps/web/src/lib/builder/description.ts"),
    Path("apps/web/src/lib/preview/fixtures.ts"),
    Path("apps/web/src/app/consent/[token]/ConsentForm.tsx"),
    Path("apps/web/src/app/onboarding/[step]/page.tsx"),
    Path("apps/web/src/app/join/[token]/page.tsx"),
    Path("apps/web/src/app/app/investigations/[id]/page.tsx"),
    Path("apps/web/src/components/app/ParticipantForm.tsx"),
    Path("apps/web/src/components/console/ActivityPanels.tsx"),
    Path("packages/domain/src/pramana_domain/library.py"),
    Path("packages/domain/src/pramana_domain/builder.py"),
    Path("services/core/src/pramana_core/language/speakable.py"),
    Path("services/core/src/pramana_core/voice/call.py"),
)


@dataclass(frozen=True, order=True)
class ReviewRow:
    language: str
    path: str
    context: str
    text: str
    spoken: str = "not spoken"


def _clean_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", "<br>")


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _language(key: str) -> str:
    return LANGUAGE_NAMES.get(key, "Hindi or Marathi, classify")


def _walk_localized(value: Any, path: Path, context: tuple[str, ...], rows: set[ReviewRow]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            name = str(key)
            if name in LANGUAGE_KEYS and isinstance(child, str):
                rows.add(
                    ReviewRow(
                        _language(name),
                        _relative(path),
                        ".".join((*context, name)),
                        child,
                    )
                )
            else:
                _walk_localized(child, path, (*context, name), rows)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_localized(child, path, (*context, str(index)), rows)
    elif isinstance(value, str) and DEVANAGARI.search(value):
        rows.add(
            ReviewRow(
                "Hindi or Marathi, classify",
                _relative(path),
                ".".join(context) or "unkeyed text",
                value,
            )
        )


def _node_string(node: ast.expr) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _node_string(node.left), _node_string(node.right)
        return left + right if left is not None and right is not None else None
    if isinstance(node, ast.JoinedStr):
        pieces: list[str] = []
        for item in node.values:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                pieces.append(item.value)
            elif isinstance(item, ast.FormattedValue):
                source = ast.unparse(item.value)
                pieces.append("{" + source + "}")
            else:
                return None
        return "".join(pieces)
    return None


def _python_localized(path: Path, rows: set[ReviewRow]) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key_node, value_node in zip(node.keys, node.values, strict=True):
            key = key_node.value if isinstance(key_node, ast.Constant) else None
            if key not in LANGUAGE_KEYS:
                continue
            text = _node_string(value_node)
            if text:
                rows.add(
                    ReviewRow(
                        _language(key),
                        _relative(path),
                        f"localized mapping at line {node.lineno}.{key}",
                        text,
                    )
                )


def _decode_js_string(raw: str) -> str:
    if raw.startswith('"'):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return raw[1:-1]
    if raw.startswith("'"):
        try:
            return ast.literal_eval(raw)
        except (SyntaxError, ValueError):
            return raw[1:-1]
    return raw[1:-1]


def _guess_language(text: str) -> str:
    normalized = text.casefold()
    if text.strip() in {"हिन्दी", "हिंदी"}:
        return "Hindi"
    if text.strip() == "मराठी":
        return "Marathi"
    if any(token in normalized for token in (" mein ", " nahi", "haan", "aap", "mera", "phone ")):
        return "Hinglish"
    if any(token in text for token in ("आहे", "इथे", "तुम्ही", "वाटतं", "तुमच्या")):
        return "Marathi"
    if any(token in text for token in ("है", "आप", "आपकी", "क्या", "में")):
        return "Hindi"
    if DEVANAGARI.search(text):
        return "Hindi or Marathi, classify"
    return "Hinglish"


def _typescript_rows(path: Path, rows: set[ReviewRow]) -> None:
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        localized_values: set[tuple[str, str]] = set()
        for match in JS_LANGUAGE_KEY.finditer(line):
            raw_key = match.group("key").strip("\"'")
            value_match = JS_STRINGS.search(line, match.end())
            if value_match:
                localized_values.add((raw_key, _decode_js_string(value_match.group(0))))
        for key, text in localized_values:
            rows.add(
                ReviewRow(
                    _language(key),
                    _relative(path),
                    f"line {line_number}, language key {key}",
                    text,
                )
            )

        for value_match in JS_STRINGS.finditer(line):
            text = _decode_js_string(value_match.group(0))
            is_preview_transcript = path.name == "fixtures.ts" and "transcript:" in line
            if not DEVANAGARI.search(text) and not is_preview_transcript:
                continue
            if any(text == localized for _, localized in localized_values):
                continue
            context = line.strip()[:140] or "string literal"
            rows.add(
                ReviewRow(
                    _guess_language(text),
                    _relative(path),
                    f"line {line_number}: {context}",
                    text,
                )
            )


def _structured_rows(rows: set[ReviewRow]) -> None:
    for path in sorted((ROOT / "packs").rglob("*.yaml")):
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        _walk_localized(value, path, (), rows)
    template_dir = ROOT / "packages/domain/src/pramana_domain/templates"
    for path in sorted(template_dir.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        _walk_localized(value, path, (), rows)


def _visible_code_rows(rows: set[ReviewRow]) -> None:
    for relative in CODE_FILES:
        path = ROOT / relative
        if not path.is_file():
            continue
        if path.suffix == ".py":
            _python_localized(path, rows)
        else:
            _typescript_rows(path, rows)

    from pramana_core.consent import _message

    consent_path = ROOT / "services/core/src/pramana_core/consent.py"
    for code, language in (("hi", "Hindi"), ("mr", "Marathi")):
        subject, body = _message(code, "{CONSENT_LINK}")
        rows.add(
            ReviewRow(
                language,
                _relative(consent_path),
                f"consent email subject, language {code}",
                subject,
            )
        )
        rows.add(
            ReviewRow(
                language,
                _relative(consent_path),
                f"consent email body, language {code}",
                body,
            )
        )


def _runtime_questions(rows: set[ReviewRow]) -> None:
    pack = load_pack("campus_block_c")
    source = "packs/campus_block_c.yaml"
    for language in LANGUAGES:
        for probe in pack.probes:
            for binding in probe.observes:
                for requires_move in (False, True):
                    action = ProbeAction(
                        participant_id="p_review",
                        probe_id=probe.id,
                        location_id=binding.at,
                        requires_move=requires_move,
                    )
                    base = realize(pack, action, language)
                    for confirmation in (False, True):
                        display = CONFIRM_PREFIX[language] + base if confirmation else base
                        form = ("move" if requires_move else "direct") + (
                            " confirmation" if confirmation else ""
                        )
                        rows.add(
                            ReviewRow(
                                _language(language),
                                source,
                                f"probe {probe.id} at {binding.at}, {form}",
                                display,
                                speakable(display, language),
                            )
                        )
        for token in pack.presence_tokens:
            display = realize_challenge(pack, token.id, token.at, language)
            rows.add(
                ReviewRow(
                    _language(language),
                    source,
                    f"presence check {token.id} at {token.at}",
                    display,
                    speakable(display, language),
                )
            )


def render_review_sheet() -> str:
    rows: set[ReviewRow] = set()
    _structured_rows(rows)
    _visible_code_rows(rows)
    _runtime_questions(rows)
    lines = [
        "<!-- Generated by scripts/generate_language_review.py; do not edit by hand. -->",
        "# Hindi, Marathi, and Hinglish language review",
        "",
        "**Every row is unchecked.** A native reviewer should check displayed and spoken text,",
        "record their role and date, and propose a corrected line where needed. No native review",
        "or endorsement is implied by generating this packet.",
        "",
        "The packet covers localized values in the shipped packs and builder templates, visible",
        "web copy and consent email, preview transcripts, voice consent, and runtime campus",
        "questions. Templates retain placeholders so reviewers can see the actual source wording.",
        "Rows labelled `Hindi or Marathi, classify` need the reviewer to identify the language.",
        "",
        (
            "| Language | Source path and context | Exact display or spoken text | "
            "Spoken rendering | Reviewer status |"
        ),
        "| --- | --- | --- | --- | --- |",
    ]
    for row in sorted(rows):
        lines.append(
            "| "
            + " | ".join(
                _clean_cell(value)
                for value in (
                    row.language,
                    f"`{row.path}`: {row.context}",
                    row.text,
                    row.spoken,
                    "unchecked",
                )
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the Hindi, Marathi, and Hinglish review packet"
    )
    parser.add_argument("--check", action="store_true", help="fail if the committed sheet is stale")
    args = parser.parse_args(argv)
    sheet = render_review_sheet()
    if args.check:
        current = (
            OUTPUT.read_text(encoding="utf-8").replace("\r\n", "\n") if OUTPUT.exists() else ""
        )
        if current != sheet:
            print(f"{OUTPUT.name} is out of date; run without --check", file=sys.stderr)
            return 1
        return 0
    OUTPUT.write_text(sheet, encoding="utf-8", newline="\n")
    print(
        f"Wrote {OUTPUT.relative_to(ROOT).as_posix()} with "
        f"{sheet.count('unchecked')} unchecked review entries"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
