import time
import uuid
from contextvars import ContextVar
from urllib.parse import urlparse

import structlog
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from apps.shared.metrics import accumulator
from apps.shared.persistence.sql_stats import (
    read_request_stats,
    report_heavy_request,
    start_request_stats,
)

log = structlog.get_logger(__name__)

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


def _route_template(request: Request) -> str | None:
    """The matched route's template with every prefix on it — ``/console/admins/{email}``, the
    low-cardinality label the metrics count under. ``None`` when nothing matched.

    Since FastAPI 0.137 ``include_router`` keeps the child router instead of cloning its path
    operations under the prefix, so ``scope["route"]`` is the route *as the child declared it* and
    its ``.path`` has lost the prefix (``/admins/{email}``, or ``""`` for the prefix itself). The
    assembled template lives on the effective route context FastAPI stashes in the scope; that
    context has no public accessor yet, hence the plain dict reads, with the route's own path as
    the fallback (the two coincide for a route declared straight on the app).
    """
    context = request.scope.get("fastapi", {}).get("effective_route_context")
    template = getattr(context, "path_format", None)
    if template is not None:
        return template
    return getattr(request.scope.get("route"), "path", None)


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


def _is_traced(request: Request, status: int) -> bool:
    """Whether this exchange earns a timeline line. Everything the *user* asked for does; what
    the browser fetched on its own — a static bundle, the favicon, a ``/.well-known`` probe —
    does not, since a row per image would bury the traffic it sits between. A 5xx is our fault
    whoever asked, so it is traced regardless."""
    path = request.url.path
    return status >= 500 or not (_is_asset(path) or _is_infra_probe(path))


def _feeds_load_metrics(request: Request, status: int) -> bool:
    """Which requests count toward ``/console/load``. Same universe as the timeline: our own
    traffic and our own failures, never the noise. 2xx/3xx and every 5xx always count; a 4xx
    (all of ``unmatched`` — a 404 before routing — plus matched 4xx) counts only when it's a
    dead link from ourselves, so bot scans, the favicon probe and stray URLs stay out."""
    return status < 400 or status >= 500 or _is_internal_dead_link(request, status)


# What refused this exchange, set by the exception handlers that shape the answer and read by the
# one line that reports it. A contextvar rather than a return value because the two are three
# layers apart: the handler runs under Starlette's ExceptionMiddleware, well below this one — and
# on the *same* task, which is exactly what plain-ASGI middlewares buy (see the class docstring).
_rejection: ContextVar[str | None] = ContextVar("labase_rejection", default=None)


def note_rejection(detail: str) -> None:
    """Record why this exchange was refused, for ``request.finished`` to carry.

    Called instead of logging a line of its own: a refusal that wrote one left the timeline saying
    the same exchange twice, once with the status and once with the reason.
    """
    _rejection.set(detail)


def _refused_deliberately(status: int) -> bool:
    """Whether a 4xx is something we refused rather than something that is simply not there.

    Every 4xx but ``404``: a 401, a 403, a 409, a 422 all say *we would not do that*, which is the
    warning half of the doctrine — the code could not carry the exchange through and answered with
    something. A 404 says there is nothing at that address, which for a stray URL or a bot scan is
    not ours to fix; ``_is_internal_dead_link`` is what promotes the ones that are.
    """
    return 400 <= status < 500 and status != 404


def new_request_id() -> str:
    """A whole UUIDv7 for the request — the base's one key shape (the v4 carve-out is for security
    tokens, and this is not one: it is echoed back in ``X-Request-ID``).

    Whole, because truncating to 8 hex chars at the source cost 32 bits: a birthday collision lands
    around 77k requests, and the Logs screen correlates on this exact value — two unrelated requests
    would merge under one filter. ``_short`` shortens it for display, which is where that helps.

    Time-ordered, because an id read off a log line then tells you *when*, and its index grows by
    append instead of splitting pages at random — the same reason every pk here is a v7."""
    return str(uuid.uuid7())


class RequestLogger:
    """Per-request correlation and telemetry (README: observability is built in).

    Binds a ``request_id`` in a contextvar so every log line of the request correlates, times the
    request, and feeds the load metrics. It logs **once per served request**, under one name —
    ``request.finished`` — whose *level* carries the outcome: ``error`` on a 5xx (our own bug or an
    exception nobody handled), ``warning`` on a refusal we made or a dead link from one of our own
    pages, ``info`` on everything else. It carries the refusal's ``detail`` too, which is all a
    second line about the same exchange ever added. This is the ``http`` source of the timeline,
    and the only one: a line written anywhere else is ``app``.

    **A plain ASGI middleware, not a ``BaseHTTPMiddleware``.** That base runs the rest of the app
    in a *child task*, which gets a copy of the context — so the ``user_id``/``org_id`` that auth
    and organizations bind while serving the request never travel back up here, and the finished
    line named neither. Awaiting the app directly keeps one context for the whole exchange, and the
    same move puts the exception on this frame: a handler that raises now leaves its line (at
    ``error``) before the exception carries on to Starlette's 500 handler, which is what turns it
    into an issue. Both properties are lost again the moment a ``BaseHTTPMiddleware`` is mounted
    *underneath* this one, hence the ones next to it in the stack are plain ASGI too.

    What the browser fetches on its own leaves nothing behind — static assets, the favicon and
    ``/.well-known`` probes — unless it 5xx'd, which is our fault whatever asked for it.
    Liveness/readiness probes are skipped before any of this.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in _SKIP_PATHS:
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        request_id = new_request_id()
        structlog.contextvars.clear_contextvars()
        # These ride every log line *and* every business event of this request (the journal's
        # write path reads them off these contextvars). The name is bound here, before the app
        # runs, because a fact emitted mid-request must already carry it — the matched route
        # template is only readable afterwards, and the raw path is what a reader wants anyway.
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            ip=request.client.host if request.client else None,
            request_name=f"{request.method} {request.url.path}",
        )
        start_request_stats()
        _rejection.set(None)

        status = 500  # what Starlette answers if the app raises before saying otherwise
        start = time.perf_counter()

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        except Exception:
            # The line first, then the exception on its way: it is the 500 handler further up
            # that captures it as an issue, and this middleware's job is only to say the exchange
            # ended — which is exactly what used to go missing on the requests that mattered most.
            self._finish(request, status, start)
            raise
        self._finish(request, status, start)

    def _finish(self, request: Request, status: int, start: float) -> None:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        self._observe(request, status, duration_ms)
        # Before the exchange line, and only when there is a surprise: the elaboration comes
        # first, the line that closes the exchange last.
        report_heavy_request()
        self._log_finished(request, status, duration_ms)

    @staticmethod
    def _observe(request: Request, status: int, duration_ms: float) -> None:
        """Feed the load metrics under the matched route template — a low-cardinality label the
        router only fills in while serving, hence read here rather than up front."""
        if not _feeds_load_metrics(request, status):
            return
        route = _route_template(request)
        if route is not None:
            accumulator.observe(request.method, route, status, duration_ms)
        else:
            # No route matched: record the real path (bounded by the accumulator) rather
            # than an opaque label, so a genuine dead link from ourselves is identifiable.
            accumulator.observe(
                request.method, request.url.path, status, duration_ms, unmatched=True
            )

    @staticmethod
    def _log_finished(request: Request, status: int, duration_ms: float) -> None:
        """Emit the request's single line, or nothing when the browser asked for it itself."""
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
