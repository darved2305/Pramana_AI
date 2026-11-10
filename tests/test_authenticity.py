"""Nothing is scripted, faked or typed in by hand where the product claims to compute it.

These checks guard the claims in README "What is real, what is simulated":

* the engine and core decide from evidence, never from a building-specific answer key;
* the core cannot read the sealed fault, and revealing it ends the scenario first;
* the product web build has no sample-data mode, and the voice service defaults to Gnani;
* headline numbers in the README match the generated reports they cite;
* committed voice rehearsal summaries say their participants were synthetic.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from pramana_core.settings import Settings
from pramana_core.voice.gnani import provider_of
from pramana_domain import load_pack

ROOT = Path(__file__).resolve().parents[1]
DECIDING_CODE = [
    ROOT / "packages" / "engine" / "src",
    ROOT / "packages" / "domain" / "src",
    ROOT / "services" / "core" / "src",
]
ALLOWED = {
    # Spoken-answer vocabulary for Wi-Fi questions: a speech-recognition hint, not evidence or
    # a decision. Changing the live-validated vocabulary before recording is not worth the risk.
    ("conversation.py", "NAVA-WiFi"),
    # Pronunciation: equipment codes that are English words are read as words when spoken.
    ("speakable.py", "GATEWAY"),
}


def _pack_identifiers() -> set[str]:
    pack = load_pack("campus_block_c")
    ids: set[str] = set(pack.component_by_id) | set(pack.location_by_id)
    for action in pack.actions:
        ids.add(action.id)
        ids.update(action.decision_classes)
    for comp in pack.components:
        for mode in getattr(comp, "modes", None) or []:
            ids.add(f"{comp.id}.{getattr(mode, 'id', mode)}")
    for probe in pack.probes:
        ids.add(probe.id)
    ids.add("NAVA-WiFi")  # the simulated building's network name
    # Probe kinds ("wifi_status", "ap_light") are the pack schema's vocabulary, not answers.
    return {i for i in ids if len(i) > 3} - {p.kind for p in pack.probes}


def _code_strings(path: Path) -> list[tuple[int, str]]:
    """String literals that are code, not docstrings."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list):
            for stmt in body:
                if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
                    docstrings.add(id(stmt.value))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_deciding_code_holds_no_building_specific_answers() -> None:
    """No fault, component, place, probe or decision of the simulated building is written into
    the engine, physics or core. A hard-coded ``if decision == "DISPATCH_..."`` would fail."""
    ids = _pack_identifiers()
    pattern = re.compile(
        r"(?<![A-Za-z0-9_])(" + "|".join(sorted(map(re.escape, ids), key=len, reverse=True)) + r")"
        r"(?![A-Za-z0-9_])"
    )
    found = []
    for root in DECIDING_CODE:
        for path in sorted(root.rglob("*.py")):
            for line, text in _code_strings(path):
                for match in pattern.finditer(text):
                    if (path.name, match.group(1)) not in ALLOWED:
                        found.append(f"{path.relative_to(ROOT)}:{line}: {match.group(1)}")
    assert found == []


def test_the_core_has_no_way_to_read_the_sealed_truth() -> None:
    """No call to the simulator's oracle route and no oracle key, in code (docstrings may say
    so). The import contract in pyproject.toml already keeps ``pramana_sim`` out of the core."""
    core = ROOT / "services" / "core" / "src"
    for path in core.rglob("*.py"):
        strings = [text for _, text in _code_strings(path)]
        assert not any("/truth" in t or "oracle" in t.lower() for t in strings), path
        names = [
            n.id if isinstance(n, ast.Name) else n.attr
            for n in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(n, ast.Name | ast.Attribute)
        ]
        assert not any("oracle" in name.lower() for name in names), path
    fields = {f.alias or name for name, f in Settings.model_fields.items()}
    assert not any("ORACLE" in f.upper() for f in fields)


def test_revealing_closes_the_scenario_first_so_peeking_ends_it() -> None:
    path = ROOT / "services" / "core" / "src" / "pramana_core" / "investigations.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    reveal = next(
        n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == "reveal"
    )
    source = ast.unparse(reveal)
    assert source.index("self.sim.close(") < source.index("self.sim.reveal(")
    assert "INVESTIGATION_ACTIVE" in source


def test_the_voice_service_defaults_to_gnani_and_the_emulator_is_not_shipped() -> None:
    default = Settings.model_fields["gnani_base_url"].default
    assert provider_of(default) == "gnani"
    shipped = ROOT / "services" / "core" / "src"
    assert not any("FakeGnani" in p.read_text(encoding="utf-8") for p in shipped.rglob("*.py"))


def test_only_the_ui_test_build_can_show_sample_data() -> None:
    gate = (ROOT / "apps" / "web" / "src" / "lib" / "store" / "local.ts").read_text(
        encoding="utf-8"
    )
    assert 'process.env.NEXT_PUBLIC_ENABLE_PREVIEW === "1"' in gate
    product_builds = [
        ROOT / "apps" / "web" / "playwright.real.config.ts",
        ROOT / "scripts" / "staging.py",
    ]
    for path in product_builds:
        text = path.read_text(encoding="utf-8")
        assert re.search(r"NEXT_PUBLIC_ENABLE_PREVIEW\W+0", text), path
        assert not re.search(r"NEXT_PUBLIC_ENABLE_PREVIEW\W+1", text), path


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


BENCHMARK_REPORT = "eval/reports/benchmark-2026-11-07-rc1"


def test_readme_benchmark_numbers_match_the_generated_report() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    summary = json.loads((ROOT / BENCHMARK_REPORT / "summary.json").read_text(encoding="utf-8"))
    p = summary["policies"]
    assert f"(`{BENCHMARK_REPORT}/`, {p['E_ours']['n']} simulated scenarios)" in readme
    for key in ("E_ours", "A_checklist", "C_random", "D_greedy_entropy"):
        assert _pct(p[key]["success_rate"]) in readme, key


@pytest.mark.parametrize(
    "path", sorted((ROOT / "eval" / "reports").glob("*/voice-*.json")), ids=lambda p: p.name
)
def test_committed_voice_rehearsals_say_the_speakers_were_synthetic(path: Path) -> None:
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["participants"] == "synthetic voice bots"
    assert "answers" not in summary  # private speech detail stays out of committed reports
