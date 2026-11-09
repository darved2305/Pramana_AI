from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_migrations_have_one_head_after_production_merge() -> None:
    core_dir = Path(__file__).resolve().parents[1]
    config = Config(str(core_dir / "alembic.ini"))
    config.set_main_option("script_location", str(core_dir / "alembic"))

    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["0020"]
    assert script.get_current_head() == "0020"
    assert script.get_revision("0020").down_revision == "0019"
