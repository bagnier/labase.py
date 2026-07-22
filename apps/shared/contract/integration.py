from pathlib import Path

import structlog
from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from apps.shared.config import get_technical_settings
from apps.shared.email import EMAIL_SEND_TOPIC, deliver_queued_email
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
from apps.shared.http.static import CachingStaticFiles
from apps.shared.observability.firehose import FirehoseWriter
from apps.shared.observability.logging import setup_logging
from apps.shared.observability.request import RequestLogger
from apps.shared.queue import TaskWorker, ensure_scheduled, register_task_handler
from apps.shared.tailer import EventTailer

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

    # Async substrate: one task worker per process; recurring jobs planted at startup.
    register_task_handler(PURGE_TOPIC, purge_counters)
    register_task_handler(EMAIL_SEND_TOPIC, deliver_queued_email)
    worker = TaskWorker(settings.task_worker_interval_seconds)
    host.on_startup(_plant_recurring_tasks)
    host.on_startup(worker.start)
    host.on_shutdown(worker.stop)

    # Event tailer: reads the business_events log and fans each fact out to its async consumers
    # (NOTIFY-woken, poll as a net). One per process, like the worker.
    tailer = EventTailer(settings.task_worker_interval_seconds)
    host.on_startup(tailer.start)
    host.on_shutdown(tailer.stop)

    # Firehose drains off the request path: the log processor only enqueues; this task writes.
    firehose_writer = FirehoseWriter(settings.firehose_flush_seconds)
    host.on_startup(firehose_writer.start)
    host.on_shutdown(firehose_writer.stop)

    app.mount(
        "/static",
        CachingStaticFiles(directory=str(_STATIC_DIR), max_age=settings.static_cache_seconds),
        name="static",
    )

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
