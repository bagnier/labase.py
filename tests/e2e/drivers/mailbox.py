"""Mailpit client — the HTTP face of the local Supabase mail catcher.

One mailbox for everything: the app's SmtpMailer and GoTrue both deliver over
SMTP (127.0.0.1:54325), both E2E drivers assert real deliveries through this
API (127.0.0.1:54324). Assertions match on a per-scenario unique marker (an
invitation token) so runs and worktrees sharing the catcher never collide.
"""

import re
import time
from datetime import datetime

import httpx

MAILPIT_URL = "http://127.0.0.1:54324"

_TOKEN_HASH = re.compile(r"token_hash=([A-Za-z0-9_-]+)")


def wait_for_message(
    to: str, containing: str, timeout: float = 10.0, since: datetime | None = None
) -> dict:
    """Return the first message to `to` whose text body contains `containing`.

    Polls: delivery happens in a server-side background task after the HTTP
    response. `since` skips messages older than the current scenario (the
    catcher accumulates across runs). Raises AssertionError on deadline.
    """
    deadline = time.monotonic() + timeout
    with httpx.Client(base_url=MAILPIT_URL, timeout=5.0) as client:
        while True:
            summaries = (
                client.get("/api/v1/search", params={"query": f"to:{to}"})
                .raise_for_status()
                .json()
                .get("messages", [])
            )
            for summary in summaries:
                if since is not None:
                    created = datetime.fromisoformat(summary["Created"])
                    if created < since:
                        continue
                detail = client.get(f"/api/v1/message/{summary['ID']}").raise_for_status().json()
                if containing in (detail.get("Text") or ""):
                    return detail
            if time.monotonic() > deadline:
                raise AssertionError(f"no mail to {to} containing {containing!r} within {timeout}s")
            time.sleep(0.3)


def token_hash_from_mail(email: str, since: datetime) -> str:
    """token_hash from the freshest GoTrue mail (recovery, email change…) to `email`."""
    message = wait_for_message(to=email, containing="token_hash=", since=since)
    match = _TOKEN_HASH.search(message.get("Text") or "")
    assert match, f"no token_hash in mail: {message.get('Text')!r}"
    return match.group(1)


def recovery_token(email: str, since: datetime) -> str:
    """token_hash from the freshest GoTrue recovery mail sent to `email` this scenario."""
    return token_hash_from_mail(email, since)


def assert_invitation_delivered(email: str, token: str | None) -> None:
    """Shared by both driver mixins: the invitation email really reached the inbox."""
    assert token, "no invitation token captured by the driver"
    message = wait_for_message(to=email, containing=token)
    assert "invited" in message.get("Subject", "").lower(), message.get("Subject")
