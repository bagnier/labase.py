"""The request middleware: writes ``request.finished``, binds the ids every other line correlates
on, and offers each exchange to the load metrics.

Most of it decides what is worth a line (AGENTS: nothing escapes the log chain). The same
predicates decide what counts as load, so metrics measure our traffic, not whatever scanned us.
"""

import time
import uuid
from contextvars import ContextVar
from typing import Protocol
from urllib.parse import urlparse

import structlog
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from apps.shared.persistence.sql_stats import (
    read_request_stats,
    report_heavy_request,
    start_request_stats,
)

log = structlog.get_logger(__name__)

_HEALTH_PROBE_PATHS = {"/health/live", "/health/ready"}
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


def _route_template(request: Request) -> str | None:
    """The matched route's full template, ``/console/admins/{email}``, or ``None``.

    ``scope["route"].path`` lacks the router prefix: FastAPI's ``include_router`` keeps the child
    route as declared. The full template is on the scope's effective route context, which has no
    public accessor.
    """
    context = request.scope.get("fastapi", {}).get("effective_route_context")
    template = getattr(context, "path_format", None)
    if template is not None:
        return template
    return getattr(request.scope.get("route"), "path", None)


def _is_asset(path: str) -> bool:
    return path == "/favicon.ico" or path.startswith("/static/") or path.endswith(_ASSET_SUFFIXES)


def _is_infra_probe(path: str) -> bool:
    """Chrome's devtools probe, ACME challenges: never one of our links."""
    return path.startswith(_INFRA_PROBE_PREFIXES)


def _is_health_probe(path: str) -> bool:
    return path in _HEALTH_PROBE_PATHS


def _is_internal_referer(request: Request) -> bool:
    referer = request.headers.get("referer")
    return bool(referer) and urlparse(referer).hostname == request.url.hostname


def _is_internal_dead_link(request: Request, status: int) -> bool:
    """A 4xx reached from one of our own pages: a bug, unlike a bot scan or a stray URL."""
    path = request.url.path
    return (
        400 <= status < 500
        and _is_internal_referer(request)
        and not _is_asset(path)
        and not _is_infra_probe(path)
    )


def _is_traced(request: Request, status: int) -> bool:
    """Whether the exchange earns a line: not what the browser fetched on its own, nor a healthy
    probe, unless it failed on our side."""
    path = request.url.path
    if _is_health_probe(path):
        return status >= 400
    return status >= 500 or not (_is_asset(path) or _is_infra_probe(path))


def _feeds_load_metrics(request: Request, status: int) -> bool:
    """Whether the exchange counts toward ``/console/load``: everything but health probes, and a
    4xx only when it is our own dead link."""
    path = request.url.path
    if _is_health_probe(path):
        return False
    return status < 400 or status >= 500 or _is_internal_dead_link(request, status)


class RequestObserver(Protocol):
    """Called once per exchange counted as load. ``label`` is the route template, or the raw
    path when ``unmatched``. Positional-only, so a subscriber names its parameters freely."""

    def __call__(
        self,
        method: str,
        label: str,
        status_code: int,
        duration_ms: float,
        /,
        *,
        unmatched: bool = False,
    ) -> None: ...


# (AGENTS: load metrics belong to their app alone)
_observers: list[RequestObserver] = []


def on_request_measured(observer: RequestObserver) -> None:
    """Subscribe ``observer`` to every exchange that counts as load."""
    _observers.append(observer)


# Set by the exception handlers, layers below, on the same task (see ``RequestLogger``).
_rejection: ContextVar[str | None] = ContextVar("labase_rejection", default=None)


def note_rejection(detail: str) -> None:
    """Have ``request.finished`` carry why the exchange was refused, instead of a second line."""
    _rejection.set(detail)


def _refused_deliberately(status: int) -> bool:
    """Every 4xx but 404: a refusal is a warning; a 404 is a warning only as our own dead link."""
    return 400 <= status < 500 and status != 404


def new_request_id() -> str:
    """A whole UUIDv7: the Timeline filters on this exact value, and 8 hex chars would collide
    around 77k requests. Shortened for display only."""
    return str(uuid.uuid7())


class RequestLogger:
    """Per-request correlation and telemetry (AGENTS: facts, traces, bugs: three records).

    Plain ASGI, not ``BaseHTTPMiddleware``, which runs the app in a child task: the
    ``user_id``/``org_id`` bound below would not reach this frame, nor would a handler's exception
    before Starlette's 500 handler. A ``BaseHTTPMiddleware`` mounted underneath breaks both too.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        request_id = new_request_id()
        structlog.contextvars.clear_contextvars()
        # Read by every log line and by the journal's writer: bound before the app runs, so a
        # fact emitted mid-request carries them.
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            ip=request.client.host if request.client else None,
            request_name=f"{request.method} {request.url.path}",
        )
        # A probe's `SELECT 1` on a slow database would trip `db.heavy_request` with nothing to
        # correlate it to.
        if not _is_health_probe(request.url.path):
            start_request_stats()
        _rejection.set(None)

        status = 500  # Starlette's answer if the app raises before starting a response
        start = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except BaseException:
            # The 500 handler above turns the exception into an issue; this only writes the line.
            # ``BaseException``: a client disconnect raises ``CancelledError`` through here.
            self._finish(request, status, start)
            raise
        self._finish(request, status, start)

    def _finish(self, request: Request, status: int, start: float) -> None:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        self._observe(request, status, duration_ms)
        # Before the line that closes the exchange.
        report_heavy_request()
        self._log_finished(request, status, duration_ms)

    @staticmethod
    def _observe(request: Request, status: int, duration_ms: float) -> None:
        """Offer the exchange to the observers, each isolated: a failing one must not replace the
        exchange's exception nor cost its line."""
        if not _feeds_load_metrics(request, status):
            return
        route = _route_template(request)
        if route is not None:
            label, unmatched = route, False
        else:
            # The observer decides how many raw paths it keeps before collapsing them.
            label, unmatched = request.url.path, True
        for observe in _observers:
            try:
                observe(request.method, label, status, duration_ms, unmatched=unmatched)
            except Exception:
                log.exception("request.observer_failed", observer=repr(observe))

    @staticmethod
    def _log_finished(request: Request, status: int, duration_ms: float) -> None:
        """``error`` on a 5xx, ``warning`` on a refusal or our dead link, ``info`` otherwise."""
        if not _is_traced(request, status):
            return
        db = read_request_stats()
        detail = _rejection.get()
        log_at = log.error if status >= 500 else log.info
        if _refused_deliberately(status) or _is_internal_dead_link(request, status):
            log_at = log.warning
        log_at(
            "request.finished",
            method=request.method,
            path=request.url.path,
            status=status,
            duration_ms=duration_ms,
            referer=request.headers.get("referer"),
            db_queries=db.count if db else 0,
            db_ms=round(db.total_ms, 1) if db else 0.0,
            **({"detail": detail} if detail is not None else {}),
        )
