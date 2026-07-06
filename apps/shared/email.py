"""Transactional email: `Mailer` port + SMTP adapter + `email.send` queue topic.

Sending never blocks a mutation — but unlike auditing it is not fire-and-forget:
callers outbox the mail with :func:`enqueue_email` through their own session, so
the task exists iff the business transaction commits, and the ``TaskWorker``
delivers it with the queue's retry-then-park semantics. The process-wide mailer
is swappable clock-style — tests install a recording fake through `set_mailer`.

Dev: the Supabase mail catcher (Mailpit) receives SMTP on localhost:54325 and
serves the same inbox as GoTrue auth mail on http://localhost:54324.
Prod: point the SMTP_* env vars at any provider — no vendor SDK.
"""

from dataclasses import asdict, dataclass
from email.message import EmailMessage
from typing import Any, Protocol

import aiosmtplib
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.config import get_technical_settings
from apps.shared.queue import enqueue

log = structlog.get_logger("labase.shared.email")


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    text: str
    html: str | None = None


class Mailer(Protocol):
    async def send(self, email: Email) -> None: ...


class SmtpMailer:
    def __init__(
        self,
        host: str,
        port: int,
        sender: str,
        username: str = "",
        password: str = "",
        start_tls: bool = False,
    ) -> None:
        self.host = host
        self.port = port
        self.sender = sender
        self.username = username
        self.password = password
        self.start_tls = start_tls

    def _message(self, email: Email) -> EmailMessage:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = email.to
        message["Subject"] = email.subject
        message.set_content(email.text)
        if email.html:
            message.add_alternative(email.html, subtype="html")
        return message

    async def send(self, email: Email) -> None:
        await aiosmtplib.send(
            self._message(email),
            hostname=self.host,
            port=self.port,
            username=self.username or None,
            password=self.password or None,
            start_tls=self.start_tls or None,
        )


_mailer: Mailer | None = None


def get_mailer() -> Mailer:
    global _mailer
    if _mailer is None:
        settings = get_technical_settings()
        _mailer = SmtpMailer(
            host=settings.smtp_host,
            port=settings.smtp_port,
            sender=settings.smtp_sender,
            username=settings.smtp_username,
            password=settings.smtp_password,
            start_tls=settings.smtp_starttls,
        )
    return _mailer


def set_mailer(mailer: Mailer | None) -> None:
    """Swap the process-wide mailer (None restores the env-configured SMTP one)."""
    global _mailer
    _mailer = mailer


EMAIL_SEND_TOPIC = "email.send"


async def enqueue_email(session: AsyncSession, email: Email) -> None:
    """Outbox `email` through the caller's session — it is sent iff the transaction commits."""
    await enqueue(session, EMAIL_SEND_TOPIC, asdict(email))


async def deliver_queued_email(_session: AsyncSession, payload: dict[str, Any]) -> None:
    """``email.send`` task handler — raises on failure so the queue retries, then parks."""
    email = Email(**payload)
    await get_mailer().send(email)
    log.info("email.sent", to=email.to, subject=email.subject)
