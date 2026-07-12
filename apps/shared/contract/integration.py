from pathlib import Path

import structlog
from fastapi import HTTPException
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from apps.shared.config import get_technical_settings
from apps.shared.email import EMAIL_SEND_TOPIC, deliver_queued_email
from apps.shared.events import BusinessEvent
from apps.shared.host import Host, MountPhase
from apps.shared.http.exceptions import (
    handle_http_error,
    handle_rate_limit,
    handle_stale_data,
    handle_unhandled_error,
)
from apps.shared.http.limiter import (
    PURGE_EVERY_SECONDS,
    PURGE_TOPIC,
    RateLimitExceeded,
    purge_counters,
)
from apps.shared.http.security import cors_config, csrf_protect, security_headers
from apps.shared.observability.business_events import persist_business_event
from apps.shared.observability.logging import setup_logging
from apps.shared.observability.request import RequestLogger
from apps.shared.queue import TaskWorker, ensure_scheduled, register_task_handler

PHASE = MountPhase.FOUNDATION

_STATIC_DIR = Path(__file__).parents[3] / "static"


def mount(host: Host) -> None:
    setup_logging()
    settings = get_technical_settings()
    app = host.app

    app.exception_handler(RateLimitExceeded)(handle_rate_limit)
    app.exception_handler(StaleDataError)(handle_stale_data)
    app.exception_handler(500)(handle_unhandled_error)
    app.exception_handler(HTTPException)(handle_http_error)
    app.exception_handler(StarletteHTTPException)(handle_http_error)

    app.middleware("http")(security_headers)
    app.middleware("http")(csrf_protect)
    app.add_middleware(RequestLogger)
    app.add_middleware(CORSMiddleware, **cors_config(settings.cors_origins))

    # Every emitted business event is recorded (non-blocking) to the business_events store —
    # one subscriber on the base type, reached for all subclasses via the bus's MRO dispatch.
    host.events.on(BusinessEvent, persist_business_event)

    # Async substrate: one task worker per process; recurring jobs planted at startup.
    register_task_handler(PURGE_TOPIC, purge_counters)
    register_task_handler(EMAIL_SEND_TOPIC, deliver_queued_email)
    worker = TaskWorker(settings.task_worker_interval_seconds)
    host.on_startup(_plant_recurring_tasks)
    host.on_startup(worker.start)
    host.on_shutdown(worker.stop)

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    host.reserve("static", "api")  # infra-owned slugs (StaticFiles mount + reserved API namespace)


async def _plant_recurring_tasks() -> None:
    """Best-effort: a missing DB at startup must not prevent serving (probes, unit runs)."""
    try:
        await ensure_scheduled(PURGE_TOPIC, PURGE_EVERY_SECONDS)
    except Exception:
        structlog.get_logger("labase.shared.queue").warning("queue.plant_recurring_failed")
