"""Sending email. One small interface, a Gmail transport, and a fake for tests."""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol
from uuid import UUID

from pydantic import SecretStr

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


class Mailer(Protocol):
    def send(self, to: str, subject: str, text: str, *, outbox_id: UUID | None = None) -> None:
        """Deliver one plain text message, or raise. Blocking: call it from a worker thread."""
        ...


@dataclass(frozen=True)
class GmailSmtp:
    """Gmail over STARTTLS with an App Password. Sends as the Gmail address itself."""

    address: str
    app_password: SecretStr
    timeout_s: float = 5.0

    def send(self, to: str, subject: str, text: str, *, outbox_id: UUID | None = None) -> None:
        message = EmailMessage()
        message["From"] = self.address
        message["To"] = to
        message["Subject"] = subject
        if outbox_id is not None:
            # SMTP has no idempotency key. A stable message id lets downstream mail systems and
            # support staff correlate any duplicate caused by a crash after SMTP accepted it.
            message["Message-ID"] = f"<pramana-{outbox_id}@mail.pramana.ai>"
            message["X-Pramana-Outbox-ID"] = str(outbox_id)
        message.set_content(text)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=self.timeout_s) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(self.address, self.app_password.get_secret_value())
            smtp.send_message(message)


@dataclass
class FakeMailer:
    """Records what would have been sent. Set ``fail`` to an exception to make sending raise."""

    sent: list[tuple[str, str, str]] = field(default_factory=list)
    outbox_ids: list[UUID | None] = field(default_factory=list)
    fail: Exception | None = None

    def send(self, to: str, subject: str, text: str, *, outbox_id: UUID | None = None) -> None:
        if self.fail is not None:
            raise self.fail
        self.sent.append((to, subject, text))
        self.outbox_ids.append(outbox_id)
