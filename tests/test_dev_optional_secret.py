"""Empty optional vault keys behave as unset while production remains strict."""

import pytest
from pydantic import ValidationError

from pramana_core.settings import Settings


def test_empty_vault_key_is_unset_in_dev():
    settings = Settings(
        PRAMANA_MODE="dev",
        DATABASE_URL="postgresql+asyncpg://x/db",
        SIM_OPERATOR_KEY="x",
        PARTICIPANT_SIGNING_KEY="x",
        PRAMANA_PII_KEY="",
        _env_file=None,
    )
    assert settings.pii_master_key is None


def test_empty_vault_key_is_rejected_in_production():
    with pytest.raises(ValidationError, match="production requires PRAMANA_PII_KEY"):
        Settings(
            PRAMANA_MODE="production",
            DATABASE_URL="postgresql+asyncpg://x/db",
            SIM_OPERATOR_KEY="x",
            PARTICIPANT_SIGNING_KEY="x",
            PRAMANA_PII_KEY="",
            _env_file=None,
        )


def test_blank_database_is_rejected():
    with pytest.raises(ValidationError, match="DATABASE_URL"):
        Settings(
            DATABASE_URL="   ",
            SIM_OPERATOR_KEY="x",
            PARTICIPANT_SIGNING_KEY="x",
            _env_file=None,
        )
