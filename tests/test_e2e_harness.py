import pytest
from e2e.harness import require_e2e_database_url


@pytest.mark.parametrize("url", [None, ""])
def test_e2e_database_url_must_be_explicit(url: str | None) -> None:
    with pytest.raises(ValueError, match="PRAMANA_E2E_DATABASE_URL is not set"):
        require_e2e_database_url(url)
