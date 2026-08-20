"""HTTP security middleware: response hardening headers + tokenless CSRF.

Cross-site cookie-authenticated mutations are rejected from the ``Sec-Fetch-Site``
header, so there are no CSRF tokens to plumb through forms (README: HTTP security).

Both are plain ASGI middleware rather than ``BaseHTTPMiddleware`` dispatch functions. Nothing
here needs the difference, but they sit *under* ``RequestLogger``, and that base runs what it
wraps in a child task whose context never rejoins the parent's — one of these in the stack is
enough to strip the request's ``user_id``/``org_id`` off the finished line
(see :class:`~apps.shared.logs.request.RequestLogger`).
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
    """Build the CORS middleware kwargs, refusing the wildcard-plus-credentials footgun.

    Starlette does not neutralise ``allow_origins=["*"]`` when credentials are on — it reflects
    the caller's ``Origin`` back with ``Allow-Credentials: true``, i.e. *any* site can read
    authenticated responses. So credentials are only granted to an explicit allowlist; a ``*``
    (or empty) origin list serves cross-origin reads without credentials. Production should set
    ``CORS_ORIGINS`` to the exact front-end origins that need cookie-authenticated access.
    """
    if not origins:
        # Closed default: no cross-origin access until an allowlist is configured.
        return {"allow_origins": [], "allow_credentials": False}
    if "*" in origins:
        # Wildcard grants public, credential-less reads only. Pairing "*" with credentials would
        # let any site read cookie-authenticated responses, so credentials are dropped here.
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
    """Stamp the hardening headers on every response, whatever produced it."""

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
    """CSRF check for cookie-authenticated mutations, no token plumbing.

    Browsers send `Sec-Fetch-Site` on every request; anything but
    `same-origin`/`none` (direct navigation) is a cross-site mutation. Older
    agents fall back to comparing `Origin` against the request host. Requests
    with neither header come from non-browser clients, which cookies don't
    auto-authenticate — allowed.
    """
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        return site not in _SAME_SITE_VALUES
    origin = request.headers.get("origin")
    if origin is None:
        return False
    return urlparse(origin).netloc != request.headers.get("host", "")


class CsrfProtect:
    """Reject unsafe cross-site requests (see :func:`_is_cross_site`)."""

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
