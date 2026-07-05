from typing import Any
from urllib.parse import urlparse

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse, Response

logger = structlog.get_logger("labase.shared.security")


def cors_config(origins: list[str]) -> dict[str, Any]:
    return {
        "allow_origins": origins,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }


CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' 'unsafe-eval'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'"
)


async def security_headers(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = CSP
    return response


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


async def csrf_protect(request: Request, call_next) -> Response:  # type: ignore[no-untyped-def]
    if request.method not in _SAFE_METHODS and _is_cross_site(request):
        logger.warning(
            "csrf.rejected",
            path=request.url.path,
            method=request.method,
            sec_fetch_site=request.headers.get("sec-fetch-site"),
            origin=request.headers.get("origin"),
        )
        return JSONResponse({"detail": "Cross-site request rejected"}, status_code=403)
    return await call_next(request)
