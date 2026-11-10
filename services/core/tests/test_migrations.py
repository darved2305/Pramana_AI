from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from pramana_core.migrations import migration_database_url, require_database_name

CORE = Path(__file__).resolve().parents[1]


def test_migration_url_uses_the_explicit_alembic_selection(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "DATABASE_URL=postgresql://local/from-dotenv\n"
        "PRAMANA_DB_NAMES=from-dotenv,from-env,from-config\n",
        encoding="utf-8",
    )
    assert (
        migration_database_url(
            "postgresql://local/from-config", "postgresql://local/from-env", dotenv
        )
        == "postgresql://local/from-config"
    )
    assert (
        migration_database_url(None, "postgresql://local/from-env", dotenv)
        == "postgresql://local/from-env"
    )
    assert migration_database_url(None, None, dotenv) == "postgresql://local/from-dotenv"


def test_migration_url_refuses_implicit_default(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="DATABASE_URL must explicitly select"):
        migration_database_url(None, None, tmp_path / "missing.env")

    blank = tmp_path / ".env"
    blank.write_text("DATABASE_URL=\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="DATABASE_URL must explicitly select"):
        migration_database_url(None, None, blank)


def test_database_url_must_name_a_database() -> None:
    with pytest.raises(RuntimeError, match="explicit database name"):
        require_database_name("postgresql+asyncpg://localhost")


def test_migration_url_refuses_a_database_outside_checkout_allowlist(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "DATABASE_URL=postgresql://local/selected\nPRAMANA_DB_NAMES=selected\n", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="not listed in PRAMANA_DB_NAMES"):
        migration_database_url(None, "postgresql://local/other", dotenv)


def test_alembic_has_a_single_head() -> None:
    config = Config(str(CORE / "alembic.ini"))
    config.set_main_option("script_location", str(CORE / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, f"alembic has several heads, so upgrade head is ambiguous: {heads}"
