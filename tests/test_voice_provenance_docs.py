"""Keep the generated voice provenance summary tied to committed evidence."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_voice_provenance as provenance  # noqa: E402


def test_committed_voice_provenance_is_current() -> None:
    assert provenance.main(["--check"]) == 0


def test_summary_covers_artifacts_and_labels_unknowns_without_credentials() -> None:
    text = provenance.render_summary()
    artifacts = sorted(provenance.RUN_DIR.glob("voice-*.json"))
    assert artifacts
    for artifact in artifacts:
        assert artifact.relative_to(ROOT).as_posix() in text
    assert "Synthetic voice bots" in text
    assert "One team member on an Android phone" in text
    assert "Unknown" in text
    assert "no accuracy or latency result is public" in text
    assert not re.search(r"(?i)(?:api[_-]?key|password|authorization)\s*[:=]\s*\S+", text)
    assert "Bearer " not in text
