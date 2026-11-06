from __future__ import annotations

import copy

import pytest
import yaml
from pydantic import ValidationError

from pramana_domain import DomainPack, load_pack
from pramana_domain.pack import default_packs_dir


def test_bundled_pack_defines_localized_tokens_without_values() -> None:
    pack = load_pack("campus_block_c")

    assert {token.location_id for token in pack.presence_tokens} >= {
        "IDF1",
        "IDF2",
        "DB_C2_PANEL",
    }
    for token in pack.presence_tokens:
        assert token.kind == "label_suffix"
        assert token.length == 3
        assert set(token.prompt_templates) == {"en", "hi", "mr", "hi-en"}
        assert set(token.display_templates) == {"en", "hi", "mr", "hi-en"}
        assert "value" not in token.model_dump()


def test_presence_token_rejects_embedded_value() -> None:
    with (default_packs_dir() / "campus_block_c.yaml").open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    data = copy.deepcopy(raw)
    data["presence_tokens"][0]["value"] = "K7Q"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DomainPack.model_validate(data)


def test_presence_token_templates_require_all_languages() -> None:
    with (default_packs_dir() / "campus_block_c.yaml").open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    data = copy.deepcopy(raw)
    del data["presence_tokens"][0]["prompt_templates"]["mr"]

    with pytest.raises(ValidationError, match="missing languages"):
        DomainPack.model_validate(data)
