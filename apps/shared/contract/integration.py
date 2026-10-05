"""The foundation's ``mount(host)``, run before every app (``MountPhase.FOUNDATION``): logging,
the production preflight, exception handlers, middleware, static files, and the base's own
background workers (task worker, event listener, log drain).
"""

from pathlib import Path
from typing import Any

import structlog
from fastapi import HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware

from apps.shared.email import EMAIL_SEND_TOPIC, deliver_queued_email
from apps.shared.events.listener import EventListener
from apps.shared.http.exceptions import (
    handle_http_error,
    handle_rate_limit,
    handle_stale_data,
    handle_unhandled_error,
)
from apps.shared.http.form import FormAsJson
from apps.shared.http.limiter import (
    PURGE_EVERY_SECONDS,
    PURGE_TOPIC,
    RateLimitExceeded,
    purge_counters,
)
from apps.shared.http.security import CsrfProtect, SecurityHeaders, cors_config
from apps.shared.http.static import CachingStaticFiles
from apps.shared.integration.host import Host, MountPhase
from apps.shared.logs.chain import catch_loop_exceptions, setup_logging
from apps.shared.logs.request import RequestLogger
from apps.shared.logs.sink import LogDrain
from apps.shared.queue import (
    QUEUE_PURGE_EVERY_SECONDS,
    QUEUE_PURGE_TOPIC,
    QUEUE_RETENTION_DAYS,
    TaskWorker,
    ensure_scheduled,
    purge_finished_tasks,
    register_task_handler,
)
from apps.shared.settings.env import TechnicalSettings, get_technical_settings
from apps.shared.settings.preflight import enforce_at_boot

log = structlog.get_logger(__name__)

PHASE = MountPhase.FOUNDATION

_STATIC_DIR = Path(__file__).parents[3] / "static"


def mount(host: Host) -> None:
    setup_logging()
    settings = get_technical_settings()
    enforce_at_boot(settings)
    app = host.app

    app.exception_handler(RateLimitExceeded)(handle_rate_limit)
    app.exception_handler(StaleDataError)(handle_stale_data)
    app.exception_handler(500)(handle_unhandled_error)
    app.exception_handler(HTTPException)(handle_http_error)
    app.exception_handler(StarletteHTTPException)(handle_http_error)

    # Innermost first: ``RequestLogger`` ends outermost, so a preflight CORS refuses still gets
    # its ``request.finished`` line. All plain ASGI (see ``RequestLogger``).
    app.add_middleware(FormAsJson)
    app.add_middleware(SecurityHeaders)
    app.add_middleware(CsrfProtect)
    app.add_middleware(CORSMiddleware, **cors_config(settings.cors_origins))
    app.add_middleware(RequestLogger)

    host.on_startup(catch_loop_exceptions)

    _start_task_worker(host, settings)
    _start_event_listener(host, settings)
    _start_log_drain(host, settings)

    app.mount(
        "/static",
        CachingStaticFiles(directory=str(_STATIC_DIR), max_age=settings.static_cache_seconds),
        name="static",
    )

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    host.reserve("static", "api")


def _start_task_worker(host: Host, settings: TechnicalSettings) -> None:
    register_task_handler(PURGE_TOPIC, purge_counters)
    register_task_handler(QUEUE_PURGE_TOPIC, _purge_finished_tasks)
    register_task_handler(EMAIL_SEND_TOPIC, deliver_queued_email)
    worker = TaskWorker(settings.task_worker_interval_seconds)
    host.on_startup(_plant_recurring_tasks)
    host.run_background(worker)


def _start_event_listener(host: Host, settings: TechnicalSettings) -> None:
    listener = EventListener(settings.task_worker_interval_seconds)
    host.run_background(listener)


def _start_log_drain(host: Host, settings: TechnicalSettings) -> None:
    log_drain = LogDrain(settings.firehose_flush_seconds)
    host.run_background(log_drain)


async def _purge_finished_tasks(session: AsyncSession, _payload: dict[str, Any]) -> None:
    await purge_finished_tasks(session, QUEUE_RETENTION_DAYS)


async def _plant_recurring_tasks() -> None:
    """Best effort: an unreachable database must not stop the app serving."""
    try:
        await ensure_scheduled(PURGE_TOPIC, PURGE_EVERY_SECONDS)
        await ensure_scheduled(QUEUE_PURGE_TOPIC, QUEUE_PURGE_EVERY_SECONDS)
    except Exception as exc:
        log.warning("queue.plant_recurring_failed", exc_info=exc)
