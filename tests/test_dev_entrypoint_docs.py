"""Keep the Windows dev entry point outside uv's signal-handling wrapper."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_make_dev_targets_run_python_directly_on_windows() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "ifeq ($(OS),Windows_NT)" in makefile
    assert "DEV_PYTHON := .venv/Scripts/python.exe" in makefile
    assert "DEV_PYTHON := uv run python" in makefile
    assert "$(DEV_PYTHON) scripts/dev.py" in makefile


def test_windows_direct_entrypoint_and_uv_interrupt_status_are_documented() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    handoff = (ROOT / "docs/engineering/HANDOFF.md").read_text(encoding="utf-8")

    for document in (readme, handoff):
        assert ".venv\\Scripts\\python.exe scripts\\dev.py" in document
        assert "0xC000013A" in document


def test_demo_stack_marks_the_local_voice_protocol_emulator(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import dev
    from dev import parse_args, service_env

    # A checkout .env that selects a database, so the test never depends on the developer's own.
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        "DATABASE_URL=postgresql+asyncpg://localhost/selected"
        + chr(10)
        + "PRAMANA_DB_NAMES=selected"
        + chr(10),
        encoding="utf-8",
    )

    env = service_env(parse_args(["--demo"]), base={})

    assert env["GNANI_PROTOCOL_EMULATOR"] == "true"
