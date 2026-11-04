"""The extraction report is generated from code, and the held-out set is well formed."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from pramana_domain import load_pack
from pramana_eval.extraction_eval import FIELDS, HELDOUT, load_items, main


def test_heldout_set_covers_four_languages_and_every_field() -> None:
    items = load_items(HELDOUT)
    assert len(items) == 80
    assert len({i["id"] for i in items}) == 80
    assert Counter(i["lang"] for i in items) == {"en": 20, "hi": 20, "mr": 20, "hi-en": 20}
    pack = load_pack("campus_block_c")
    for it in items:
        assert set(FIELDS) <= set(it), it["id"]
        assert it["outcome"] in [*pack.probe_by_id[it["probe"]].outcomes, "unknown"], it["id"]
        if it["injection"] or it["stop"]:
            assert it["outcome"] == "unknown", it["id"]
    kinds = Counter(
        "injection" if i["injection"] else "stop" if i["stop"] else i["directness"] for i in items
    )
    assert kinds["injection"] >= 6
    assert kinds["stop"] >= 4
    assert kinds["hearsay"] >= 4
    texts = {i["text"].casefold() for i in items}
    for short in ("haan", "nahi re", "band aahe", "chalu aahe", "हो"):
        assert short in texts


def test_report_is_written_from_the_scores(tmp_path: Path) -> None:
    main(["--set", str(HELDOUT), "--provider", "none", "--out", str(tmp_path)])
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    rules = summary["extractors"]["rules"]
    assert rules["n"] == 80
    assert set(rules["per_language"]) == {"en", "hi", "mr", "hi-en"}
    assert set(rules["per_field"]) == set(FIELDS)
    assert rules["correct"] == sum(r["ok"] for r in rules["rows"])
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert f"{rules['correct']}/80" in report
    assert "Held-out set" in report
