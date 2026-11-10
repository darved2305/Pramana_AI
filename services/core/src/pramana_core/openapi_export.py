"""Write (or check) ``services/core/openapi.json``: ``python -m pramana_core.openapi_export``."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .main import create_app
from .settings import Settings

PATH = Path(__file__).resolve().parents[2] / "openapi.json"


def build() -> dict[str, Any]:
    # Placeholder settings: the spec does not depend on secrets or connections.
    settings = Settings(
        **{  # type: ignore[arg-type]
            # Never connected to: a named database only satisfies the explicit-selection rule.
            "DATABASE_URL": "postgresql+asyncpg://openapi@localhost:5433/openapi_export",
            "SIM_OPERATOR_KEY": "x",
            "PARTICIPANT_SIGNING_KEY": "x",
            "GNANI_API_KEY": "",
            "LLM_EXTRACTOR_PROVIDER": "none",
            "LOG_JSON": False,
        }
    )
    spec: dict[str, Any] = create_app(settings).openapi()
    return spec


def render() -> str:
    return json.dumps(build(), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    text = render()
    if "--check" in argv:
        if not PATH.exists() or PATH.read_text(encoding="utf-8") != text:
            print("openapi.json is out of date; run `make openapi`", file=sys.stderr)
            return 1
        return 0
    PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
