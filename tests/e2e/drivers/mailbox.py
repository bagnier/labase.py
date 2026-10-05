"""The Mailpit client, where both the app and GoTrue deliver. Matched on a per-scenario marker,
so runs sharing the catcher do not collide.
"""

import re
import time
from datetime import datetime

import httpx

from apps.shared.settings.env import get_technical_settings

_TOKEN_HASH = re.compile(r"token_hash=([A-Za-z0-9_-]+)")


def wait_for_message(
    to: str, containing: str, timeout: float = 10.0, since: datetime | None = None
) -> dict:
    """The first mail to `to` containing `containing`, polled (delivery is asynchronous);
    `since` skips older mail. Raises AssertionError at the deadline."""
    deadline = time.monotonic() + timeout
    mailpit_url = get_technical_settings().mailpit_url
    with httpx.Client(base_url=mailpit_url, timeout=5.0) as client:
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
    message = wait_for_message(to=email, containing="token_hash=", since=since)
    match = _TOKEN_HASH.search(message.get("Text") or "")
    assert match, f"no token_hash in mail: {message.get('Text')!r}"
    return match.group(1)


def recovery_token(email: str, since: datetime) -> str:
    return token_hash_from_mail(email, since)


def assert_invitation_delivered(email: str, token: str | None) -> None:
    assert token, "no invitation token captured by the driver"
    message = wait_for_message(to=email, containing=token)
    assert "invited" in message.get("Subject", "").lower(), message.get("Subject")
