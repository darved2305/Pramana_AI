from pramana_core.openapi_export import PATH, render


def test_committed_openapi_matches_the_app() -> None:
    """Fails when routes or schemas changed without `make openapi`."""
    assert PATH.read_text(encoding="utf-8") == render()
