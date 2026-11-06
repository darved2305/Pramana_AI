"""Keep the Windows dev entry point outside uv's signal-handling wrapper."""

from pathlib import Path

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
