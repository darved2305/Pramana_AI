from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from pramana_domain import DomainPack, load_pack
from pramana_domain.pack import default_packs_dir


@pytest.fixture(scope="module")
def raw() -> dict[str, Any]:
    with (default_packs_dir() / "campus_block_c.yaml").open(encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh)
    return data


def _invalid(raw: dict[str, Any], mutate: Any, match: str) -> None:
    data = copy.deepcopy(raw)
    mutate(data)
    with pytest.raises(ValidationError, match=match):
        DomainPack.model_validate(data)


def test_bundled_pack_is_valid() -> None:
    pack = load_pack("campus_block_c")
    assert pack.pack == "campus_block_c"
    assert set(pack.decision_of) >= {"CB_C2_7.tripped", "SW_C2.dead", "NO_FAULT"}


def test_dangling_power_reference(raw: dict[str, Any]) -> None:
    def m(d: dict[str, Any]) -> None:
        next(c for c in d["components"] if c["id"] == "SW_C2")["powered_by"] = "CB_NOPE"

    _invalid(raw, m, "powered_by 'CB_NOPE' does not exist")


def test_dependency_cycle(raw: dict[str, Any]) -> None:
    def m(d: dict[str, Any]) -> None:
        next(c for c in d["components"] if c["id"] == "SW_CORE")["uplink"] = "SW_C2"

    _invalid(raw, m, "dependency cycle")


def test_yaml_boolean_outcomes_are_rejected(raw: dict[str, Any]) -> None:
    def m(d: dict[str, Any]) -> None:
        d["probes"][0]["outcomes"] = [True, False]  # what unquoted yes/no become in YAML 1.1

    _invalid(raw, m, "string")


def test_probe_outcomes_must_match_the_observable(raw: dict[str, Any]) -> None:
    def m(d: dict[str, Any]) -> None:
        next(p for p in d["probes"] if p["id"] == "nvr_screen")["outcomes"] = ["on", "booting"]

    _invalid(raw, m, "must equal")


def test_indicator_probe_needs_valid_target(raw: dict[str, Any]) -> None:
    def m(d: dict[str, Any]) -> None:
        next(p for p in d["probes"] if p["id"] == "nvr_screen")["observes"] = [
            {"at": "IDF2", "target": "SW_C2"}
        ]

    _invalid(raw, m, "invalid for powered")


def test_every_hypothesis_needs_a_decision_class(raw: dict[str, Any]) -> None:
    def m(d: dict[str, Any]) -> None:
        d["decision_classes"] = [dc for dc in d["decision_classes"] if dc["id"] != "IT_FIX_DNS"]

    _invalid(raw, m, "DNS.down has no decision class")


def test_missing_template_language(raw: dict[str, Any]) -> None:
    def m(d: dict[str, Any]) -> None:
        del d["probes"][0]["templates"]["mr"]

    _invalid(raw, m, "missing languages")


def test_unknown_role(raw: dict[str, Any]) -> None:
    def m(d: dict[str, Any]) -> None:
        d["probes"][0]["roles"] = ["wizard"]

    _invalid(raw, m, "unknown role")


def test_pack_id_cannot_escape_the_packs_directory() -> None:
    with pytest.raises(ValueError, match="invalid pack id"):
        load_pack("../secrets")


def test_walking_is_shortest_path() -> None:
    pack = load_pack("campus_block_c")
    assert pack.walk_seconds("GUARD_DESK", "IDF2") == 10 + 40 + 15
    assert pack.walk_seconds("IDF2", "IDF2") == 0
    assert pack.walk_seconds("F3_R304", "F3_R310") == 20


def test_load_by_path(tmp_path: Path) -> None:
    src = default_packs_dir() / "campus_block_c.yaml"
    dst = tmp_path / "copy.yaml"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    assert load_pack(dst).pack == "campus_block_c"
