"""The client's IP. Behind a proxy the socket peer is the proxy, so with ``TRUST_FORWARDED_FOR``
the left-most ``X-Forwarded-For`` entry is used instead (see its setting for the risk).
"""

from fastapi import Request

from apps.shared.settings.env import get_technical_settings


def client_ip(request: Request) -> str | None:
    """``None`` only when neither is available."""
    if get_technical_settings().trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            first = forwarded.split(",", 1)[0].strip()
            if first:
                return first
    return request.client.host if request.client else None
