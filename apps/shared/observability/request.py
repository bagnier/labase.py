import time
import uuid
from urllib.parse import urlparse

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from apps.shared.observability.metrics import accumulator
from apps.shared.observability.sql import read_request_stats, start_request_stats

log = structlog.get_logger("labase.http")

_SKIP_PATHS = {"/health/live", "/health/ready"}
_INFRA_PROBE_PREFIXES = ("/.well-known/",)
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


def _is_infra_probe(path: str) -> bool:
    """A path the browser or infra fetches on its own — Chrome's devtools probe, ACME
    challenges — always under ``/.well-known/``, never one of our links. Its 404 is noise
    for both the timeline and the load metrics, even with a same-host referer."""
    return path.startswith(_INFRA_PROBE_PREFIXES)


def _is_internal_referer(request: Request) -> bool:
    """Whether the request followed a link from one of our own pages — a same-host ``Referer``.
    That's what makes a 404 a *dead link from ourselves* rather than a bot scan or a stray URL."""
    referer = request.headers.get("referer")
    return bool(referer) and urlparse(referer).hostname == request.url.hostname


def _is_internal_dead_link(request: Request, status: int) -> bool:
    """A 4xx that is a dead link from ourselves — a same-host ``Referer`` to a real, non-asset,
    non-infra-probe path. The single test shared by the timeline (what to log) and the load
    metrics (what to count)."""
    path = request.url.path
    return (
        400 <= status < 500
        and _is_internal_referer(request)
        and not _is_asset(path)
        and not _is_infra_probe(path)
    )


def _feeds_load_metrics(request: Request, status: int) -> bool:
    """Which requests count toward ``/console/load``. Same universe as the timeline: our own
    traffic and our own failures, never the noise. 2xx/3xx and every 5xx always count; a 4xx
    (all of ``unmatched`` — a 404 before routing — plus matched 4xx) counts only when it's a
    dead link from ourselves, so bot scans, the favicon probe and stray URLs stay out."""
    return status < 400 or status >= 500 or _is_internal_dead_link(request, status)


def new_request_id() -> str:
    """A whole UUIDv7 for the request — the base's one key shape (the v4 carve-out is for security
    tokens, and this is not one: it is echoed back in ``X-Request-ID``).

    Whole, because truncating to 8 hex chars at the source cost 32 bits: a birthday collision lands
    around 77k requests, and the Logs screen correlates on this exact value — two unrelated requests
    would merge under one filter. ``_short`` shortens it for display, which is where that helps.

    Time-ordered, because an id read off a log line then tells you *when*, and its index grows by
    append instead of splitting pages at random — the same reason every pk here is a v7."""
    return str(uuid.uuid7())


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

        request_id = new_request_id()
        ip = request.client.host if request.client else None
        structlog.contextvars.clear_contextvars()
        # Both ride every log line *and* every business event of this request (the trail's write
        # path reads them off these contextvars). The name is bound here, before call_next, because
        # a fact emitted mid-request must already carry it — the matched route template is only
        # readable afterwards, and the raw path is what a reader wants anyway.
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            ip=ip,
            request_name=f"{request.method} {request.url.path}",
        )
        start_request_stats()

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 1)

        # The router mutates the shared scope during matching, so the matched template
        # (low-cardinality label) is only readable after call_next.
        if _feeds_load_metrics(request, response.status_code):
            route = request.scope.get("route")
            if route is not None:
                accumulator.observe(request.method, route.path, response.status_code, duration_ms)
            else:
                # No route matched: record the real path (bounded by the accumulator) rather
                # than an opaque label, so a genuine dead link from ourselves is identifiable.
                accumulator.observe(
                    request.method,
                    request.url.path,
                    response.status_code,
                    duration_ms,
                    unmatched=True,
                )

        self._log_if_failed(request, response.status_code, duration_ms)
        response.headers["X-Request-ID"] = request_id
        return response

    @staticmethod
    def _log_if_failed(request: Request, status: int, duration_ms: float) -> None:
        """Emit the single ``request.failed`` line, or nothing. 5xx logs at ``error`` (a server
        fault, correlated with its captured issue); an internal dead-link 4xx at ``warning``."""
        server_error = status >= 500
        internal_dead_link = _is_internal_dead_link(request, status)
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
