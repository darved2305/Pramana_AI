"""First-run environment generation preserves an existing checkout's settings."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("dev_env_test", ROOT / "scripts" / "dev_env.py")
assert spec
assert spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_existing_lines_survive_repeated_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / ".env.example").write_text(
        "DATABASE_URL=\nPRAMANA_DB_NAMES=\nSIM_OPERATOR_KEY=\n", encoding="utf-8"
    )
    existing = "# local notes\nCUSTOM_OPTION=hello\nPRAMANA_DB_NAMES=mine\nDATABASE_URL=postgresql+asyncpg://x/mine\n"
    path = tmp_path / ".env"
    path.write_text(existing, encoding="utf-8")
    module.main()
    first = path.read_text(encoding="utf-8")
    module.main()
    assert path.read_text(encoding="utf-8") == first
    assert first.startswith(existing)


def test_new_environment_selects_private_database(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / ".env.example").write_text("DATABASE_URL=\nPRAMANA_DB_NAMES=\n", encoding="utf-8")
    module.main()
    values = dict(line.split("=", 1) for line in (tmp_path / ".env").read_text().splitlines())
    assert values["DATABASE_URL"].endswith("/" + values["PRAMANA_DB_NAMES"])
    assert values["PRAMANA_DB_NAMES"] != "pramana"
