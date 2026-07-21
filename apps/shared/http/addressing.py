"""Resolve the originating client IP, honouring a trusted reverse proxy.

``request.client.host`` is the socket peer — behind a proxy/LB that is the proxy itself, so
every caller collapses onto one IP (a global rate-limit bucket, indistinguishable logs). When
``TRUST_FORWARDED_FOR`` is set (the deployment sits behind a proxy we control), the left-most
``X-Forwarded-For`` entry — the original client the edge observed — is used instead. Off by
default: trusting the header when nothing upstream strips it lets any caller spoof their IP.
"""

from fastapi import Request

from apps.shared.config import get_technical_settings


def client_ip(request: Request) -> str | None:
    """The caller's IP: the left-most X-Forwarded-For hop when proxy headers are trusted,
    else the socket peer. ``None`` only when neither is available (rare, non-HTTP transports)."""
    if get_technical_settings().trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            first = forwarded.split(",", 1)[0].strip()
            if first:
                return first
    return request.client.host if request.client else None
