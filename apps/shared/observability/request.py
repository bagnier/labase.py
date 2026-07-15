import time
import uuid
from urllib.parse import urlparse

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from apps.shared.observability.metrics import UNMATCHED_ROUTE, accumulator
from apps.shared.observability.sql import read_request_stats, start_request_stats

log = structlog.get_logger("labase.http")

_SKIP_PATHS = {"/health/live", "/health/ready"}
_ASSET_SUFFIXES = (
    ".ico",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".css",
    ".js",
    ".map",
    ".woff",
    ".woff2",
    ".ttf",
)


def _is_asset(path: str) -> bool:
    """A browser-fetched asset (favicon, static bundle, image/font) — never an interesting
    'dead link', so its 4xx stays out of the timeline even when the referer is ours."""
    return path == "/favicon.ico" or path.startswith("/static/") or path.endswith(_ASSET_SUFFIXES)


def _is_internal_referer(request: Request) -> bool:
    """Whether the request followed a link from one of our own pages — a same-host ``Referer``.
    That's what makes a 404 a *dead link from ourselves* rather than a bot scan or a stray URL."""
    referer = request.headers.get("referer")
    return bool(referer) and urlparse(referer).hostname == request.url.hostname


class RequestLogger(BaseHTTPMiddleware):
    """Per-request correlation and telemetry (README: observability is built in).

    Binds a short ``request_id`` in a contextvar so every log line of the request correlates, times
    the request, and feeds the load metrics. It logs **once per request, and only on failure worth
    an admin's eyes**: every 5xx (our own bug), and a 4xx only when it's a *dead link from
    ourselves* — a same-host ``Referer`` to a non-asset path. Successful requests leave no timeline
    row; they still feed ``/console/load`` and correlate through the shared ``request_id``.
    Liveness/readiness probes are skipped entirely.
    """

    async def dispatch(self, request: Request, call_next) -> Response:  # type: ignore[override]
        if request.url.path in _SKIP_PATHS:
            return await call_next(request)

        request_id = str(uuid.uuid4())[:8]
        ip = request.client.host if request.client else None
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, ip=ip)
        start_request_stats()

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)

        # The router mutates the shared scope during matching, so the template
        # (low-cardinality label) is only readable after call_next.
        route_template = getattr(request.scope.get("route"), "path", UNMATCHED_ROUTE)
        accumulator.observe(request.method, route_template, response.status_code, duration_ms)

        self._log_if_failed(request, response.status_code, duration_ms)
        response.headers["X-Request-ID"] = request_id
        return response

    @staticmethod
    def _log_if_failed(request: Request, status: int, duration_ms: float) -> None:
        """Emit the single ``request.failed`` line, or nothing. 5xx logs at ``error`` (a server
        fault, correlated with its captured issue); an internal dead-link 4xx at ``warning``."""
        server_error = status >= 500
        internal_dead_link = (
            400 <= status < 500
            and _is_internal_referer(request)
            and not _is_asset(request.url.path)
        )
        if not (server_error or internal_dead_link):
            return
        db = read_request_stats()
        log_at = log.error if server_error else log.warning
        log_at(
            "request.failed",
            method=request.method,
            path=request.url.path,
            status=status,
            duration_ms=duration_ms,
            referer=request.headers.get("referer"),
            db_queries=db.count if db else 0,
            db_ms=round(db.total_ms, 1) if db else 0.0,
        )
