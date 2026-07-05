from unittest.mock import AsyncMock, patch

import pytest

from apps.shared.email import Email, SmtpMailer, send_email, set_mailer


class FakeMailer:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[Email] = []

    async def send(self, email: Email) -> None:
        if self.fail:
            raise RuntimeError("smtp down")
        self.sent.append(email)


@pytest.fixture()
def fake_mailer():
    mailer = FakeMailer()
    set_mailer(mailer)
    yield mailer
    set_mailer(None)


_EMAIL = Email(to="bob@example.com", subject="Hello", text="Hi", html="<p>Hi</p>")


@pytest.mark.asyncio
async def test_send_email_delegates_to_mailer(fake_mailer):
    await send_email(_EMAIL)
    assert fake_mailer.sent == [_EMAIL]


@pytest.mark.asyncio
async def test_send_email_swallows_mailer_failure():
    set_mailer(FakeMailer(fail=True))
    try:
        await send_email(_EMAIL)  # must not raise: best-effort doctrine
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
