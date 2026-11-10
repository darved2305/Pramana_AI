import pytest
from fastapi import FastAPI, WebSocket
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from pramana_core import errors, observability


def test_dependency_error_does_not_log_exception_details(monkeypatch) -> None:
    entries = []
    monkeypatch.setattr(errors.log, "error", lambda *args, **kwargs: entries.append((args, kwargs)))
    app = FastAPI()
    errors.install_error_handlers(app)

    @app.get("/")
    async def endpoint() -> None:
        raise OSError("private-person@example.test: transcript secret")

    response = TestClient(app, raise_server_exceptions=False).get("/")
    assert response.status_code == 503
    assert "private-person@example.test" not in response.text
    assert "private-person@example.test" not in repr(entries)
    assert "transcript secret" not in repr(entries)


def test_unhandled_error_does_not_log_exception_details(monkeypatch) -> None:
    entries = []
    monkeypatch.setattr(errors.log, "error", lambda *args, **kwargs: entries.append((args, kwargs)))
    app = FastAPI()
    errors.install_error_handlers(app)

    @app.get("/")
    async def endpoint() -> None:
        raise RuntimeError("Riya Rao +919876543210 riya@example.test private transcript")

    response = TestClient(app, raise_server_exceptions=False).get("/")
    assert response.status_code == 500
    assert "Riya Rao" not in response.text
    assert "+919876543210" not in repr(entries)
    assert "riya@example.test" not in repr(entries)
    assert "private transcript" not in repr(entries)


def test_request_middleware_does_not_log_exception_details(monkeypatch) -> None:
    entries = []
    monkeypatch.setattr(
        observability.log, "error", lambda *args, **kwargs: entries.append((args, kwargs))
    )
    app = FastAPI()
    app.add_middleware(observability.RequestContextMiddleware)

    @app.get("/")
    async def endpoint() -> None:
        raise RuntimeError("Riya Rao +919876543210 riya@example.test private transcript")

    response = TestClient(app).get("/")
    assert response.status_code == 500
    assert "Riya Rao" not in response.text
    assert "+919876543210" not in repr(entries)
    assert "riya@example.test" not in repr(entries)
    assert "private transcript" not in repr(entries)


def test_request_middleware_contains_stream_errors_without_logging_details(monkeypatch) -> None:
    entries = []
    monkeypatch.setattr(
        observability.log, "error", lambda *args, **kwargs: entries.append((args, kwargs))
    )
    app = FastAPI()
    app.add_middleware(observability.RequestContextMiddleware)

    async def stream():
        yield b"safe prefix"
        raise RuntimeError("Riya Rao +919876543210 riya@example.test private transcript")

    @app.get("/")
    async def endpoint() -> StreamingResponse:
        return StreamingResponse(stream())

    response = TestClient(app).get("/")
    assert response.status_code == 200
    assert response.content == b"safe prefix"
    assert "Riya Rao" not in response.text
    assert "+919876543210" not in repr(entries)
    assert "riya@example.test" not in repr(entries)
    assert "private transcript" not in repr(entries)


def test_websocket_middleware_contains_errors_without_logging_details(monkeypatch) -> None:
    entries = []
    monkeypatch.setattr(
        observability.log, "error", lambda *args, **kwargs: entries.append((args, kwargs))
    )
    app = FastAPI()
    app.add_middleware(observability.RequestContextMiddleware)

    @app.websocket("/")
    async def endpoint(socket: WebSocket) -> None:
        await socket.accept()
        raise RuntimeError("Riya Rao +919876543210 riya@example.test private transcript")

    with TestClient(app).websocket_connect("/") as socket:
        response = socket.receive_json()
        assert response["type"] == "error"
        assert response["code"] == "INTERNAL"
        assert response["message"] == "internal error"
        with pytest.raises(WebSocketDisconnect) as disconnected:
            socket.receive_text()
        assert disconnected.value.code == 1011
    assert "Riya Rao" not in str(response)
    assert "+919876543210" not in repr(entries)
    assert "riya@example.test" not in repr(entries)
    assert "private transcript" not in repr(entries)
