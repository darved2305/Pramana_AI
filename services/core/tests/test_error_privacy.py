from fastapi import FastAPI
from fastapi.testclient import TestClient

from pramana_core import errors


def test_dependency_error_does_not_log_exception_details(monkeypatch) -> None:
    entries = []
    monkeypatch.setattr(errors.log, "error", lambda *args, **kwargs: entries.append((args, kwargs)))
    app = FastAPI()
    errors.install_error_handlers(app)

    @app.get("/")
    async def endpoint() -> None:
        raise OSError("private-person@example.test: transcript secret")

    response = TestClient(app).get("/")
    assert response.status_code == 503
    assert "private-person@example.test" not in response.text
    assert "private-person@example.test" not in repr(entries)
    assert "transcript secret" not in repr(entries)
