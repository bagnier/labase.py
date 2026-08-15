import json
from unittest.mock import AsyncMock, patch

import pytest

from apps.shared.email import (
    EMAIL_SEND_TOPIC,
    Email,
    SmtpMailer,
    deliver_queued_email,
    enqueue_email,
    set_mailer,
)


class FakeMailer:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[Email] = []

    async def send(self, email: Email) -> None:
        if self.fail:
            raise RuntimeError("smtp down")
        self.sent.append(email)


@pytest.fixture
def fake_mailer():
    mailer = FakeMailer()
    set_mailer(mailer)
    yield mailer
    set_mailer(None)


_EMAIL = Email(to="bob@example.com", subject="Hello", text="Hi", html="<p>Hi</p>")


@pytest.mark.asyncio
async def test_enqueue_email_outboxes_through_the_callers_session():
    session = AsyncMock()
    await enqueue_email(session, _EMAIL)

    params = session.execute.call_args.args[1]
    assert params["topic"] == EMAIL_SEND_TOPIC
    assert json.loads(params["payload"]) == {
        "to": "bob@example.com",
        "subject": "Hello",
        "text": "Hi",
        "html": "<p>Hi</p>",
    }
    assert params["user_id"] is None  # server-level work: admin session in the worker


@pytest.mark.asyncio
async def test_deliver_queued_email_sends_through_the_mailer(fake_mailer):
    await deliver_queued_email(
        AsyncMock(),
        {"to": _EMAIL.to, "subject": _EMAIL.subject, "text": _EMAIL.text, "html": _EMAIL.html},
    )
    assert fake_mailer.sent == [_EMAIL]


@pytest.mark.asyncio
async def test_deliver_queued_email_raises_so_the_queue_retries():
    set_mailer(FakeMailer(fail=True))
    try:
        with pytest.raises(RuntimeError):
            await deliver_queued_email(AsyncMock(), {"to": "a@b.c", "subject": "s", "text": "t"})
    finally:
        set_mailer(None)


@pytest.mark.asyncio
async def test_smtp_mailer_sends_multipart_message():
    mailer = SmtpMailer(host="mail.example", port=2525, sender="labase <no-reply@example.com>")
    with patch("apps.shared.email.aiosmtplib.send", new_callable=AsyncMock) as smtp_send:
        await mailer.send(_EMAIL)

    message = smtp_send.call_args.args[0]
    assert message["From"] == "labase <no-reply@example.com>"
    assert message["To"] == "bob@example.com"
    assert message["Subject"] == "Hello"
    assert message.get_body(("plain",)).get_content().strip() == "Hi"
    assert message.get_body(("html",)).get_content().strip() == "<p>Hi</p>"
    assert smtp_send.call_args.kwargs["hostname"] == "mail.example"
    assert smtp_send.call_args.kwargs["port"] == 2525
