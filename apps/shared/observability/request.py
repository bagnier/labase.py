import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from apps.shared.observability.metrics import UNMATCHED_ROUTE, accumulator
from apps.shared.observability.sql import read_request_stats, start_request_stats

log = structlog.get_logger("labase.http")

_SKIP_PATHS = {"/health/live", "/health/ready"}


class RequestLogger(BaseHTTPMiddleware):
    """Per-request correlation and telemetry (README: observability is built in).

    Binds a short ``request_id`` in a contextvar so every log line of the request correlates,
    times the request, and folds load metrics plus the SQL-query tally into ``request.finished``.
    Liveness/readiness probes are skipped to keep the logs clean.
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
        log.info(
            "request.started",
            method=request.method,
            path=request.url.path,
            ip=request.client.host if request.client else None,
        )

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        # The router mutates the shared scope during matching, so the template
        # (low-cardinality label) is only readable after call_next.
        route_template = getattr(request.scope.get("route"), "path", UNMATCHED_ROUTE)
        accumulator.observe(request.method, route_template, response.status_code, duration_ms)
        db = read_request_stats()
        log.info(
            "request.finished",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
            db_queries=db.count if db else 0,
            db_ms=round(db.total_ms, 1) if db else 0.0,
        )
        response.headers["X-Request-ID"] = request_id
        return response
