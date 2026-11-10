from __future__ import annotations

import asyncio
import logging

import pytest

from pramana_core import observability


def http_scope() -> dict[str, object]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/v1/consent-links/private-code",
        "raw_path": b"/v1/consent-links/private-code",
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "server": ("127.0.0.1", 80),
        "state": {},
    }


def test_logging_filters_only_expected_pool_cancellation() -> None:
    logger = logging.getLogger("sqlalchemy.pool.impl.AsyncAdaptedQueuePool")
    original_filters = list(logger.filters)
    cancellation = asyncio.CancelledError()
    cancelled_record = logging.LogRecord(
        name=logger.name,
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Exception terminating connection <connection>",
        args=(),
        exc_info=(asyncio.CancelledError, cancellation, None),
    )
    database_error = logging.LogRecord(
        name=logger.name,
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Exception terminating connection <connection>",
        args=(),
        exc_info=(RuntimeError, RuntimeError("database failure"), None),
    )
    unrelated_error = logging.LogRecord(
        name=logger.name,
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="Connection invalidated",
        args=(),
        exc_info=(asyncio.CancelledError, cancellation, None),
    )

    try:
        observability.configure_logging()
        pool_filter = next(
            item
            for item in logger.filters
            if isinstance(item, observability._CancelledPoolTerminationFilter)
        )
        assert not pool_filter.filter(cancelled_record)
        assert pool_filter.filter(database_error)
        assert pool_filter.filter(unrelated_error)
    finally:
        logger.filters[:] = original_filters


@pytest.mark.asyncio
async def test_request_context_does_not_log_normal_cancellation(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        observability.log,
        "exception",
        lambda *args, **kwargs: calls.append(("exception", args, kwargs)),
    )
    monkeypatch.setattr(
        observability.log, "info", lambda *args, **kwargs: calls.append(("info", args, kwargs))
    )

    async def cancelled_app(scope, receive, send):
        raise asyncio.CancelledError

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        raise AssertionError(f"unexpected response: {message}")

    with pytest.raises(asyncio.CancelledError):
        await observability.RequestContextMiddleware(cancelled_app)(http_scope(), receive, send)
    assert calls == []


@pytest.mark.asyncio
async def test_request_context_adds_request_id_and_redacts_consent_path(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        observability.log,
        "exception",
        lambda *args, **kwargs: calls.append(("exception", args, kwargs)),
    )
    monkeypatch.setattr(
        observability.log, "info", lambda *args, **kwargs: calls.append(("info", args, kwargs))
    )
    sent = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = http_scope()
    await observability.RequestContextMiddleware(app)(scope, receive, send)
    assert any(
        (b"x-request-id", value) in sent[0]["headers"]
        for value in [scope["state"]["request_id"].encode()]
    )
    assert "private-code" not in repr(calls)
    assert calls[0][0] == "info"
