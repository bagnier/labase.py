"""Transactional email: `Mailer` port + SMTP adapter.

Doctrine mirrors auditing: sending is best-effort and never blocks a mutation.
Callers enqueue `send_email` on `BackgroundTasks`; a failed send is logged and
swallowed. The process-wide mailer is swappable clock-style — tests install a
recording fake through `set_mailer`.

Dev: the Supabase mail catcher (Mailpit) receives SMTP on localhost:54325 and
serves the same inbox as GoTrue auth mail on http://localhost:54324.
Prod: point the SMTP_* env vars at any provider — no vendor SDK.
"""

from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib
import structlog

from apps.shared.config import get_technical_settings

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


async def send_email(email: Email) -> None:
    """Best-effort send, meant to run as a background task — never raises."""
    try:
        await get_mailer().send(email)
    except Exception:
        log.exception("email.send_failed", to=email.to, subject=email.subject)
    else:
        log.info("email.sent", to=email.to, subject=email.subject)
