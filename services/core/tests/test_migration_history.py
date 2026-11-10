from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_migrations_have_one_head_after_production_merge() -> None:
    core_dir = Path(__file__).resolve().parents[1]
    config = Config(str(core_dir / "alembic.ini"))
    config.set_main_option("script_location", str(core_dir / "alembic"))

    script = ScriptDirectory.from_config(config)

    heads = script.get_heads()
    assert len(heads) == 1, f"expected one migration head, found {heads}"
    assert script.get_current_head() == heads[0]
    assert script.get_revision("0022").down_revision == "0021"
    assert script.get_revision("0023").down_revision == "0022"
