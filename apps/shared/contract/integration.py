from pathlib import Path

import structlog
from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from apps.shared.config import TechnicalSettings, get_technical_settings
from apps.shared.email import EMAIL_SEND_TOPIC, deliver_queued_email
from apps.shared.events.listener import EventListener
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
from apps.shared.http.security import CsrfProtect, SecurityHeaders, cors_config
from apps.shared.http.static import CachingStaticFiles
from apps.shared.observability.firehose import FirehoseWriter
from apps.shared.observability.logging import catch_loop_exceptions, setup_logging
from apps.shared.observability.request import RequestLogger
from apps.shared.preflight import enforce_at_boot
from apps.shared.queue import TaskWorker, ensure_scheduled, register_task_handler

log = structlog.get_logger(__name__)

PHASE = MountPhase.FOUNDATION

_STATIC_DIR = Path(__file__).parents[3] / "static"


def mount(host: Host) -> None:
    setup_logging()
    settings = get_technical_settings()
    enforce_at_boot(settings)  # refuse to boot on an unsafe production config
    app = host.app

    app.exception_handler(RateLimitExceeded)(handle_rate_limit)
    app.exception_handler(StaleDataError)(handle_stale_data)
    app.exception_handler(500)(handle_unhandled_error)
    app.exception_handler(HTTPException)(handle_http_error)
    app.exception_handler(StarletteHTTPException)(handle_http_error)

    # Added innermost-first: each ``add_middleware`` wraps what is already there, so CORS ends up
    # outermost and the hardening headers closest to the router. All four are plain ASGI — a
    # ``BaseHTTPMiddleware`` anywhere under ``RequestLogger`` would run the rest in a child task
    # and strip the request's correlation off the finished line (see ``RequestLogger``).
    app.add_middleware(SecurityHeaders)
    app.add_middleware(CsrfProtect)
    app.add_middleware(RequestLogger)
    app.add_middleware(CORSMiddleware, **cors_config(settings.cors_origins))

    # The three process-wide hooks go in with setup_logging; the loop's only exists once
    # there is a loop to install it on.
    host.on_startup(catch_loop_exceptions)

    _start_task_worker(host, settings)
    _start_event_listener(host, settings)
    _start_firehose_writer(host, settings)

    app.mount(
        "/static",
        CachingStaticFiles(directory=str(_STATIC_DIR), max_age=settings.static_cache_seconds),
        name="static",
    )

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    host.reserve("static", "api")  # infra-owned slugs (StaticFiles mount + reserved API namespace)


def _start_task_worker(host: Host, settings: TechnicalSettings) -> None:
    """The async substrate: one task worker per process, and the recurring jobs it plants."""
    register_task_handler(PURGE_TOPIC, purge_counters)
    register_task_handler(EMAIL_SEND_TOPIC, deliver_queued_email)
    worker = TaskWorker(settings.task_worker_interval_seconds)
    host.on_startup(_plant_recurring_tasks)
    host.run_background(worker)


def _start_event_listener(host: Host, settings: TechnicalSettings) -> None:
    """Reads the ``business_events`` journal and fans each fact out to its consumers (NOTIFY-woken,
    polling as a net). One per process, like the worker."""
    listener = EventListener(settings.task_worker_interval_seconds)
    host.run_background(listener)


def _start_firehose_writer(host: Host, settings: TechnicalSettings) -> None:
    """Keeps the firehose off the request path: the log processor enqueues, this task writes."""
    firehose_writer = FirehoseWriter(settings.firehose_flush_seconds)
    host.run_background(firehose_writer)


async def _plant_recurring_tasks() -> None:
    """Best-effort: a missing DB at startup must not prevent serving (probes, unit runs)."""
    try:
        await ensure_scheduled(PURGE_TOPIC, PURGE_EVERY_SECONDS)
    except Exception as exc:
        log.warning("queue.plant_recurring_failed", exc_info=exc)
