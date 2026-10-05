"""Hardening headers and tokenless CSRF (AGENTS: CSRF needs no token, and the rate limiter fails
open). Plain ASGI, as everything under ``RequestLogger`` must be (see its docstring).
"""

from typing import Any
from urllib.parse import urlparse

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = structlog.get_logger(__name__)


def cors_config(origins: list[str]) -> dict[str, Any]:
    """CORS middleware kwargs: credentials only for an explicit allowlist. With ``"*"`` and
    credentials, Starlette reflects any ``Origin``, letting any site read authenticated
    responses."""
    if not origins:
        return {"allow_origins": [], "allow_credentials": False}
    if "*" in origins:
        log.warning("cors.wildcard_without_credentials")
        return {
            "allow_origins": ["*"],
            "allow_credentials": False,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }
    return {
        "allow_origins": origins,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }


_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'"
)


_HARDENING = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": _CSP,
}


class SecurityHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_hardened(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in _HARDENING.items():
                    headers[name] = value
            await send(message)

        await self.app(scope, receive, send_hardened)


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SAME_SITE_VALUES = frozenset({"same-origin", "none"})


def _is_cross_site(request: Request) -> bool:
    """``Sec-Fetch-Site`` other than ``same-origin`` or ``none`` (direct navigation); older
    browsers fall back to ``Origin`` against the host. With neither header the caller is not a
    browser, and no cookie authenticates it on its own."""
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site not in _SAME_SITE_VALUES
    origin = request.headers.get("origin")
    if origin is None:
        return False
    return urlparse(origin).netloc != request.headers.get("host", "")


class CsrfProtect:
    """Reject unsafe cross-site requests with a 403."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        if request.method not in _SAFE_METHODS and _is_cross_site(request):
            log.warning(
                "csrf.rejected",
                path=request.url.path,
                method=request.method,
                sec_fetch_site=request.headers.get("sec-fetch-site"),
                origin=request.headers.get("origin"),
            )
            refusal = JSONResponse({"detail": "Cross-site request rejected"}, status_code=403)
            await refusal(scope, receive, send)
            return
        await self.app(scope, receive, send)
