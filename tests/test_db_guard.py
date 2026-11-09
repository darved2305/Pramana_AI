"""Database resets refuse unless the URL is explicit and its database is allowlisted.

These tests never open a connection. They guard the reset paths of the core tests, the e2e
harness, the browser backend and the load test, which otherwise downgrade whatever URL they get.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from db_guard import DatabaseGuardError, require_listed_url, setting_database_url

ALLOWED = "postgresql+asyncpg://pramana@localhost:5433/pramana_tn_test"
NOT_ALLOWED = "postgresql+asyncpg://pramana@localhost:5433/pramana_web_e2e"


def test_refuses_when_the_url_is_unset(tmp_path: Path) -> None:
    with pytest.raises(DatabaseGuardError, match="TEST_DATABASE_URL is not set"):
        setting_database_url(
            "TEST_DATABASE_URL",
            environ={"PRAMANA_DB_NAMES": "pramana_tn_test"},
            dotenv_path=tmp_path / ".env",
        )


def test_refuses_when_no_database_is_allowlisted(tmp_path: Path) -> None:
    with pytest.raises(DatabaseGuardError, match="PRAMANA_DB_NAMES is not set"):
        setting_database_url(
            "TEST_DATABASE_URL",
            environ={"TEST_DATABASE_URL": ALLOWED},
            dotenv_path=tmp_path / ".env",
        )


def test_refuses_a_database_that_is_not_allowlisted(tmp_path: Path) -> None:
    with pytest.raises(DatabaseGuardError, match="database 'pramana_web_e2e': it is not listed"):
        setting_database_url(
            "TEST_DATABASE_URL",
            environ={"TEST_DATABASE_URL": NOT_ALLOWED, "PRAMANA_DB_NAMES": "pramana_tn_test"},
            dotenv_path=tmp_path / ".env",
        )


def test_accepts_an_explicit_allowlisted_database(tmp_path: Path) -> None:
    assert (
        setting_database_url(
            "TEST_DATABASE_URL",
            environ={
                "TEST_DATABASE_URL": ALLOWED,
                "PRAMANA_DB_NAMES": "pramana_tn, pramana_tn_test, pramana_tn_e2e",
            },
            dotenv_path=tmp_path / ".env",
        )
        == ALLOWED
    )


def test_reads_this_checkout_settings_when_the_environment_is_silent(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"TEST_DATABASE_URL={ALLOWED}\nPRAMANA_DB_NAMES=pramana_tn_test\n", encoding="utf-8"
    )
    assert setting_database_url("TEST_DATABASE_URL", environ={}, dotenv_path=env_file) == ALLOWED


def test_a_checkout_file_that_does_not_list_the_database_still_refuses(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"TEST_DATABASE_URL={NOT_ALLOWED}\nPRAMANA_DB_NAMES=pramana_tn_test\n", encoding="utf-8"
    )
    with pytest.raises(DatabaseGuardError, match="not listed"):
        setting_database_url("TEST_DATABASE_URL", environ={}, dotenv_path=env_file)


def test_a_url_passed_directly_is_checked_at_the_reset(tmp_path: Path) -> None:
    with pytest.raises(DatabaseGuardError, match="database 'pramana_web_e2e': it is not listed"):
        require_listed_url(
            NOT_ALLOWED, environ={"PRAMANA_DB_NAMES": "pramana_tn_test"}, dotenv_path=None
        )
    with pytest.raises(DatabaseGuardError, match="URL is empty"):
        require_listed_url("  ", environ={"PRAMANA_DB_NAMES": "pramana_tn_test"}, dotenv_path=None)


def test_query_parameters_do_not_change_the_database_name(tmp_path: Path) -> None:
    url = f"{ALLOWED}?ssl=disable"
    assert (
        require_listed_url(url, environ={"PRAMANA_DB_NAMES": "pramana_tn_test"}, dotenv_path=None)
        == url
    )
