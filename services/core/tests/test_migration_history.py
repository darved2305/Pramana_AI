from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_migrations_have_one_head() -> None:
    core_dir = Path(__file__).resolve().parents[1]
    config = Config(str(core_dir / "alembic.ini"))
    config.set_main_option("script_location", str(core_dir / "alembic"))

    script = ScriptDirectory.from_config(config)

    heads = script.get_heads()
    assert len(heads) == 1, f"migration history forks into heads {heads}"
    assert script.get_current_head() == heads[0]
