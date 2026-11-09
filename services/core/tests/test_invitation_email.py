"""Emailing invitation links: truthful reporting, never failing the invitation, no real email."""

from __future__ import annotations

import smtplib
import threading
import uuid
from datetime import timedelta
from types import TracebackType
from typing import Any, ClassVar, Self

import pytest
from auth_testkit import CSRF
from core_testkit import core_settings
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_accounts import account_core as account_core
from test_accounts import create
from test_google_auth import sql

from pramana_core import outbox
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
    app.state.email_relay.mailer = mailer
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
    assert body["email_delivery"] == "queued"
    assert len(mailer.sent) == 1
    to, subject, text = mailer.sent[0]
    assert to == "new.person@example.com"
    assert "Pramana" in subject
    assert f"https://pramana.example{body['accept_path']}" in text
    listed = client.get(f"/v1/orgs/{org}/invitations").json()
    assert listed[0]["email_delivery"] == "sent"


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


def test_revoking_a_queued_invitation_purges_its_email(
    account_core: TestClient, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = account_core
    org = workspace(client)
    mailer = FakeMailer()
    configure(client, mailer, "https://pramana.example")
    relay = client.app.state.email_relay

    async def no_op() -> dict[str, int | bool]:
        return {"locked": True, "sent": 0, "retried": 0, "dead": 0}

    monkeypatch.setattr(relay, "drain", no_op)
    created = post(client, f"/v1/orgs/{org}/invitations", INVITE)
    invitation_id = created.json()["invitation"]["id"]
    assert created.status_code == 201
    assert post(client, f"/v1/orgs/{org}/invitations/{invitation_id}/revoke", {}).status_code == 204
    queued = sql(
        migrated_db,
        "select state, recipient, subject, body, last_error from email_outbox",
    )
    assert queued == [
        {
            "state": "dead",
            "recipient": None,
            "subject": None,
            "body": None,
            "last_error": "InvitationNoLongerValid",
        }
    ]
    monkeypatch.undo()
    assert client.portal.call(relay.drain)["sent"] == 0
    assert mailer.sent == []


def test_expired_invitation_is_dead_lettered_without_sending(
    account_core: TestClient, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = account_core
    org = workspace(client)
    mailer = FakeMailer()
    configure(client, mailer, "https://pramana.example")
    relay = client.app.state.email_relay

    async def no_op() -> dict[str, int | bool]:
        return {"locked": True, "sent": 0, "retried": 0, "dead": 0}

    monkeypatch.setattr(relay, "drain", no_op)
    assert post(client, f"/v1/orgs/{org}/invitations", INVITE).status_code == 201
    sql(
        migrated_db,
        "update invitations set expires_at = now() - interval '1 second' where email = :email",
        {"email": INVITE["email"]},
    )
    monkeypatch.undo()
    result = client.portal.call(relay.drain)
    assert result["dead"] == 1
    assert mailer.sent == []
    dead = sql(migrated_db, "select state, body, last_error from email_outbox")
    assert dead == [{"state": "dead", "body": None, "last_error": "InvitationNoLongerValid"}]


def test_without_gmail_email_is_failed_and_the_owner_can_share_the_link(
    account_core: TestClient,
) -> None:
    client = account_core
    org = workspace(client)
    configure(client, None, None)
    r = post(client, f"/v1/orgs/{org}/invitations", INVITE)
    assert r.status_code == 201
    assert r.json()["email_delivery"] == "failed"
    assert r.json()["accept_path"].startswith("/invite/org_")
    assert client.get(f"/v1/orgs/{org}/invitations").json()[0]["email_delivery"] == "failed"


def test_smtp_failure_is_retried_and_does_not_store_error_text(
    account_core: TestClient, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = account_core
    org = workspace(client)
    monkeypatch.setattr(outbox, "_backoff", lambda _: timedelta(seconds=60))
    mailer = FakeMailer(
        fail=smtplib.SMTPException("smtp said no: not-a-real-password /invite/org_abc")
    )
    configure(
        client,
        mailer,
        "https://pramana.example",
    )
    r = post(client, f"/v1/orgs/{org}/invitations", INVITE)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email_delivery"] == "queued"
    listed = client.get(f"/v1/orgs/{org}/invitations").json()
    assert listed[0]["status"] == "pending"
    assert listed[0]["email_delivery"] == "queued"
    assert mailer.sent == []
    sql(migrated_db, "update email_outbox set available_at = now() where state = 'queued'")
    attempts = sql(
        migrated_db,
        "select result, error_type from email_outbox_attempts order by attempt",
    )
    assert attempts == [{"result": "retry", "error_type": "SMTPException"}]
    assert "smtp said no" not in repr(attempts)

    # A later request can wake the relay after backoff; the first message is sent once it succeeds.
    mailer.fail = None
    other = {"email": "second.person@example.com", "roles": ["viewer"]}
    assert post(client, f"/v1/orgs/{org}/invitations", other).status_code == 201
    assert len(mailer.sent) == 2
    listed = client.get(f"/v1/orgs/{org}/invitations").json()
    assert {item["email_delivery"] for item in listed} == {"sent"}


def test_committed_email_survives_a_crash_before_the_relay_runs(
    account_core: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = account_core
    org = workspace(client)
    mailer = FakeMailer()
    configure(client, mailer, "https://pramana.example")
    relay = client.app.state.email_relay

    async def crash_before_send() -> dict[str, int | bool]:
        return {"locked": True, "sent": 0, "retried": 0, "dead": 0}

    monkeypatch.setattr(relay, "drain", crash_before_send)
    r = post(client, f"/v1/orgs/{org}/invitations", INVITE)
    assert r.status_code == 201
    assert r.json()["email_delivery"] == "queued"
    assert mailer.sent == []
    queued = client.get(f"/v1/orgs/{org}/invitations").json()
    assert queued[0]["email_delivery"] == "queued"

    monkeypatch.undo()
    other = {"email": "wake.relay@example.com", "roles": ["viewer"]}
    assert post(client, f"/v1/orgs/{org}/invitations", other).status_code == 201
    assert len(mailer.sent) == 2


def test_only_one_relay_sends_at_a_time(
    account_core: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = account_core
    org = workspace(client)
    entered = threading.Event()
    release = threading.Event()

    class BlockingMailer(FakeMailer):
        def send(
            self, to: str, subject: str, text: str, *, outbox_id: uuid.UUID | None = None
        ) -> None:
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test send was not released")
            super().send(to, subject, text, outbox_id=outbox_id)

    mailer = BlockingMailer()
    configure(client, mailer, "https://pramana.example")
    relay = client.app.state.email_relay

    async def no_op() -> dict[str, int | bool]:
        return {"locked": True, "sent": 0, "retried": 0, "dead": 0}

    monkeypatch.setattr(relay, "drain", no_op)
    assert post(client, f"/v1/orgs/{org}/invitations", INVITE).status_code == 201
    monkeypatch.undo()

    future = client.portal.start_task_soon(relay.drain)
    assert entered.wait(3)
    second = client.portal.call(relay.drain)
    assert second["locked"] is False
    release.set()
    result = future.result(timeout=5)
    assert result["sent"] == 1
    assert len(mailer.sent) == 1


def test_relay_drains_bounded_batches_for_generic_email_kinds(
    account_core: TestClient, migrated_db: str
) -> None:
    client = account_core
    org = workspace(client)
    org_id = sql(migrated_db, "select id from organizations where slug = :slug", {"slug": org})[0][
        "id"
    ]
    mailer = FakeMailer()
    configure(client, mailer, "https://pramana.example")
    outbox_ids = [uuid.uuid4() for _ in range(outbox.MAX_MESSAGES_PER_DRAIN + 1)]
    for index, outbox_id in enumerate(outbox_ids):
        sql(
            migrated_db,
            "insert into email_outbox "
            "(id, org_id, kind, state, recipient, subject, body) "
            "values (:id, :org, 'notice', 'queued', :recipient, 'Hello', 'Message body')",
            {
                "id": outbox_id,
                "org": org_id,
                "recipient": f"person{index}@example.test",
            },
        )

    relay = client.app.state.email_relay
    first = client.portal.call(relay.drain)
    assert first["sent"] == outbox.MAX_MESSAGES_PER_DRAIN
    assert len(mailer.sent) == outbox.MAX_MESSAGES_PER_DRAIN
    queued = sql(migrated_db, "select count(*) as count from email_outbox where state = 'queued'")
    assert queued[0]["count"] == 1

    second = client.portal.call(relay.drain)
    assert second["sent"] == 1
    assert len(mailer.sent) == len(outbox_ids)
    assert set(mailer.outbox_ids) == set(outbox_ids)


def test_dead_letter_is_visible_and_message_body_is_purged(
    account_core: TestClient, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = account_core
    org = workspace(client)
    monkeypatch.setattr(outbox, "MAX_ATTEMPTS", 2)
    monkeypatch.setattr(outbox, "_backoff", lambda _: timedelta(seconds=60))
    mailer = FakeMailer(fail=smtplib.SMTPException("private transport details"))
    configure(client, mailer, "https://pramana.example")

    assert post(client, f"/v1/orgs/{org}/invitations", INVITE).status_code == 201
    sql(migrated_db, "update email_outbox set available_at = now() where state = 'queued'")
    second = {"email": "dead.letter@example.com", "roles": ["viewer"]}
    assert post(client, f"/v1/orgs/{org}/invitations", second).status_code == 201
    listed = client.get(f"/v1/orgs/{org}/invitations").json()
    by_email = {item["email"]: item["email_delivery"] for item in listed}
    assert by_email[INVITE["email"]] == "failed"
    assert by_email[second["email"]] == "queued"
    dead = sql(
        migrated_db,
        "select state, body, recipient, last_error from email_outbox where state = 'dead'",
    )
    assert dead == [
        {"state": "dead", "body": None, "recipient": None, "last_error": "SMTPException"}
    ]
    assert "private transport details" not in repr(dead)


def test_a_crash_after_smtp_acceptance_is_recorded_as_uncertain(
    account_core: TestClient, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = account_core
    org = workspace(client)
    mailer = FakeMailer()
    configure(client, mailer, "https://pramana.example")
    relay = client.app.state.email_relay
    monkeypatch.setattr(outbox, "LOCK_LEASE", timedelta(0))

    async def no_op() -> dict[str, int | bool]:
        return {"locked": True, "sent": 0, "retried": 0, "dead": 0}

    monkeypatch.setattr(relay, "drain", no_op)
    assert post(client, f"/v1/orgs/{org}/invitations", INVITE).status_code == 201
    monkeypatch.undo()
    monkeypatch.setattr(outbox, "LOCK_LEASE", timedelta(0))

    async def crash_after_send(_: Any, __: Any) -> None:
        raise RuntimeError("simulated database failure after SMTP acceptance")

    monkeypatch.setattr(relay, "_finish_success", crash_after_send)
    with pytest.raises(RuntimeError, match="simulated database failure"):
        client.portal.call(relay.drain)
    monkeypatch.undo()

    result = client.portal.call(relay.drain)
    assert result["sent"] == 1
    assert len(mailer.sent) == 2
    assert mailer.outbox_ids[0] == mailer.outbox_ids[1]
    attempts = sql(
        migrated_db,
        "select attempt, result from email_outbox_attempts order by attempt",
    )
    assert attempts == [
        {"attempt": 1, "result": "uncertain"},
        {"attempt": 2, "result": "sent"},
    ]


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
        sent = ("send", message["To"], message["Subject"])
        message_id = message.get("Message-ID")
        self.calls.append((*sent, message_id) if message_id else sent)


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


def test_gmail_message_uses_a_stable_outbox_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", RecordingSmtp)
    outbox_id = uuid.uuid4()
    GmailSmtp("sender@gmail.com", SecretStr("app-pass")).send(
        "to@example.com", "Hi", "Text", outbox_id=outbox_id
    )
    sent = RecordingSmtp.instances[-1].calls[-2]
    assert sent == ("send", "to@example.com", "Hi", f"<pramana-{outbox_id}@mail.pramana.ai>")


def test_a_line_break_in_an_address_cannot_add_a_header(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smtplib, "SMTP", RecordingSmtp)
    before = len(RecordingSmtp.instances)
    with pytest.raises(ValueError):
        GmailSmtp("sender@gmail.com", SecretStr("x")).send("a\nBcc: b@x.y", "Hi", "Text")
    assert len(RecordingSmtp.instances) == before
