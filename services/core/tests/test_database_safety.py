import pytest
from core_testkit import require_test_database_url


def test_core_test_database_requires_an_explicit_url() -> None:
    with pytest.raises(pytest.fail.Exception, match="TEST_DATABASE_URL is not set"):
        require_test_database_url("")
