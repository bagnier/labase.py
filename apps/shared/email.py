"""Transactional email: the ``Mailer`` port, its SMTP adapter, and the ``email.send`` queue topic.

Callers outbox a mail with :func:`enqueue_email` on their own session; the queue delivers it with
retries, then parks it. Tests swap the mailer with :func:`set_mailer`. In development Mailpit
catches the mail; production points ``SMTP_*`` at any provider.
"""

from dataclasses import asdict, dataclass
from email.message import EmailMessage
from typing import Any, Protocol

import aiosmtplib
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.queue import enqueue
from apps.shared.settings.env import get_technical_settings

log = structlog.get_logger(__name__)


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
        *,
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
    """Queue ``email`` on the caller's session: it is sent iff that transaction commits."""
    await enqueue(session, EMAIL_SEND_TOPIC, asdict(email))


async def deliver_queued_email(_session: AsyncSession, payload: dict[str, Any]) -> None:
    """The ``email.send`` handler; raises so the queue retries."""
    email = Email(**payload)
    await get_mailer().send(email)
