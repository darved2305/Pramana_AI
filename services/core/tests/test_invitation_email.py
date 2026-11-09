"""Emailing invitation links: truthful reporting, never failing the invitation, no real email."""

from __future__ import annotations

import smtplib
import time
import uuid
from types import TracebackType
from typing import Any, ClassVar, Self

import pytest
from auth_testkit import CSRF
from core_testkit import core_settings
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_accounts import account_core as account_core
from test_accounts import create

from pramana_core import invitations
from pramana_core.mail import FakeMailer, GmailSmtp

pytestmark = pytest.mark.db


def post(client: TestClient, path: str, json: Any, key: str | None = None) -> Any:
    headers = {**CSRF, "Idempotency-Key": key or uuid.uuid4().hex}
    return client.post(path, json=json, headers=headers)


def workspace(client: TestClient) -> str:
    return str(create(client).json()["organization"]["slug"])


def configure(client: TestClient, mailer: FakeMailer | None, base: str | None) -> None:
    app: Any = client.app
    app.state.mailer = mailer
    app.state.settings = app.state.settings.model_copy(
        update={
            "gmail_address": "sender@gmail.com" if base else None,
            "gmail_app_password": SecretStr("not-a-real-password") if base else None,
            "public_web_url": base,
        }
    )


INVITE = {"email": "new.person@example.com", "roles": ["operator"]}


def test_the_link_is_emailed_when_gmail_is_set_up(account_core: TestClient) -> None:
    client = account_core
    org = workspace(client)
    mailer = FakeMailer()
    configure(client, mailer, "https://pramana.example/")
    r = post(client, f"/v1/orgs/{org}/invitations", INVITE)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email_delivery"] == "sent"
    assert len(mailer.sent) == 1
    to, subject, text = mailer.sent[0]
    assert to == "new.person@example.com"
    assert "Pramana" in subject
    assert f"https://pramana.example{body['accept_path']}" in text


def test_a_retry_replays_without_sending_again(account_core: TestClient) -> None:
    client = account_core
    org = workspace(client)
    mailer = FakeMailer()
    configure(client, mailer, "https://pramana.example")
    key = uuid.uuid4().hex
    first = post(client, f"/v1/orgs/{org}/invitations", INVITE, key)
    again = post(client, f"/v1/orgs/{org}/invitations", INVITE, key)
    assert again.status_code == 201
    assert again.headers["idempotent-replayed"] == "true"
    assert again.json() == first.json()
    assert len(mailer.sent) == 1


def test_without_gmail_the_owner_shares_the_link(account_core: TestClient) -> None:
    client = account_core
    org = workspace(client)
    configure(client, None, None)
    r = post(client, f"/v1/orgs/{org}/invitations", INVITE)
    assert r.status_code == 201
    assert r.json()["email_delivery"] == "not_configured"
    assert r.json()["accept_path"].startswith("/invite/org_")


def test_a_send_failure_keeps_the_invitation_and_never_logs_the_secret(
    account_core: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = account_core
    org = workspace(client)
    logged: list[tuple[str, dict[str, Any]]] = []

    class Recorder:
        def warning(self, event: str, **values: Any) -> None:
            logged.append((event, values))

    monkeypatch.setattr(invitations, "log", Recorder())
    configure(
        client,
        FakeMailer(fail=smtplib.SMTPException("smtp said no: not-a-real-password /invite/org_abc")),
        "https://pramana.example",
    )
    r = post(client, f"/v1/orgs/{org}/invitations", INVITE)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email_delivery"] == "failed"
    listed = client.get(f"/v1/orgs/{org}/invitations").json()["items"]
    assert [i["status"] for i in listed] == ["pending"]
    secret = str(body["accept_path"]).rpartition(".")[2]
    text = repr(logged)
    assert secret not in text
    assert "not-a-real-password" not in text
    assert "/invite/" not in text
    assert [event for event, _ in logged] == ["invitation_email_not_confirmed"]
    assert logged[0][1]["error"] == "SMTPException"


def test_a_slow_send_does_not_hold_the_request(
    account_core: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = account_core
    org = workspace(client)

    class Slow(FakeMailer):
        def send(self, to: str, subject: str, text: str) -> None:
            time.sleep(2)

    monkeypatch.setattr(invitations, "SEND_TIMEOUT_S", 0.2)
    configure(client, Slow(), "https://pramana.example")
    started = time.monotonic()
    r = post(client, f"/v1/orgs/{org}/invitations", INVITE)
    assert r.status_code == 201
    assert r.json()["email_delivery"] == "failed"
    assert time.monotonic() - started < 1.9


def test_settings_only_report_ready_when_complete_and_safe() -> None:
    base = core_settings("postgresql+asyncpg://x@localhost/x")
    complete = {
        "gmail_address": "sender@gmail.com",
        "gmail_app_password": SecretStr("x"),
        "public_web_url": "https://a.example/",
    }
    assert base.model_copy(update=complete).invitation_link_base == "https://a.example"
    missing = {**complete, "gmail_app_password": None}
    assert base.model_copy(update=missing).invitation_link_base is None
    plain = {**complete, "public_web_url": "http://a.example"}
    assert base.model_copy(update=plain).invitation_link_base == "http://a.example"
    production = {**plain, "mode": "production"}
    assert base.model_copy(update=production).invitation_link_base is None
    assert base.invitation_link_base is None


class RecordingSmtp:
    instances: ClassVar[list[RecordingSmtp]] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.calls: list[Any] = [("connect", host, port, timeout)]
        RecordingSmtp.instances.append(self)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, a: type[BaseException] | None, b: BaseException | None, c: TracebackType | None
    ) -> None:
        self.calls.append("quit")

    def starttls(self, context: Any = None) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", user, password))

    def send_message(self, message: Any) -> None:
        self.calls.append(("send", message["To"], message["Subject"]))


def test_gmail_transport_uses_starttls_with_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", RecordingSmtp)
    GmailSmtp("sender@gmail.com", SecretStr("app-pass")).send("to@example.com", "Hi", "Text")
    assert RecordingSmtp.instances[-1].calls == [
        ("connect", "smtp.gmail.com", 587, 5.0),
        "starttls",
        ("login", "sender@gmail.com", "app-pass"),
        ("send", "to@example.com", "Hi"),
        "quit",
    ]


def test_a_line_break_in_an_address_cannot_add_a_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", RecordingSmtp)
    before = len(RecordingSmtp.instances)
    with pytest.raises(ValueError):
        GmailSmtp("sender@gmail.com", SecretStr("x")).send("a\nBcc: b@x.y", "Hi", "Text")
    assert len(RecordingSmtp.instances) == before
