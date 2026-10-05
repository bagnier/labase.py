"""Fixed-window rate limiting, counted in a shared Postgres table so limits hold across
instances (AGENTS: CSRF needs no token, and the rate limiter fails open).
"""

import asyncio
import functools
from collections.abc import Callable
from typing import Any

import structlog
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared import clock
from apps.shared.http.client_ip import client_ip
from apps.shared.logs.dependency import log_dependency_failure
from apps.shared.persistence.database import admin_session_factory
from apps.shared.settings.env import get_technical_settings

log = structlog.get_logger(__name__)


class UnlimitedEndpoint(Exception):
    """A ``@rate_limit`` endpoint without a ``request`` parameter, hence unlimited. Raised and
    caught to open an issue."""


def _report_unlimited_endpoint(scope: str, func: Any) -> None:
    try:
        raise UnlimitedEndpoint(f"{getattr(func, '__qualname__', func)} takes no request")
    except UnlimitedEndpoint as exc:
        log.exception("rate_limit.no_request", exc_info=exc, scope=scope)


_PERIOD_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}

_INCREMENT = text(
    "INSERT INTO rate_limit_counters (key, window_start, count) "
    "VALUES (:key, to_timestamp(:window_start), 1) "
    "ON CONFLICT (key, window_start) "
    "DO UPDATE SET count = rate_limit_counters.count + 1 "
    "RETURNING count"
)
PURGE_TOPIC = "rate_limit.purge"
PURGE_EVERY_SECONDS = 3600


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("rate limit exceeded")
        self.retry_after = retry_after


def _parse(limit_string: str) -> tuple[int, int]:
    """'10/minute' → (10, 60)."""
    count, _, period = limit_string.partition("/")
    return int(count), _PERIOD_SECONDS[period]


async def _increment(key: str, window_seconds: int) -> int | None:
    """Hits in the current window, this one included; ``None`` if the store failed."""
    epoch = int(clock.now().timestamp())
    window_start = epoch - (epoch % window_seconds)
    try:
        # Failing open only helps if it is fast: a store that never answers is bounded too.
        async with asyncio.timeout(get_technical_settings().rate_limit_store_timeout_seconds):
            async with admin_session_factory()() as session:
                hits = await session.scalar(_INCREMENT, {"key": key, "window_start": window_start})
                await session.commit()
                return int(hits or 0)
    except Exception as exc:
        # Fail open, but as an issue: an unlimited server must not go unnoticed.
        log_dependency_failure(log, "rate_limit.store_failed", exc, key=key)
        return None


async def purge_counters(session: AsyncSession, _payload: dict[str, Any]) -> None:
    """Recurring task: delete windows older than any limit."""
    await session.execute(
        text("DELETE FROM rate_limit_counters WHERE window_start < now() - interval '1 day'")
    )


def rate_limit(limit_string: str) -> Callable[[Any], Any]:
    """Limit an endpoint per client IP; it must take a `request: Request` parameter."""
    max_hits, window_seconds = _parse(limit_string)

    def decorator(func: Any) -> Any:
        # Module-qualified: two routers' `create` handlers must not share a bucket.
        scope = f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not get_technical_settings().rate_limit_enabled:
                return await func(*args, **kwargs)
            request: Request | None = kwargs.get("request") or next(
                (a for a in args if isinstance(a, Request)), None
            )
            if request is None:
                _report_unlimited_endpoint(scope, func)
                return await func(*args, **kwargs)
            ip = client_ip(request)
            if ip is None:
                log.warning("rate_limit.no_client_ip", scope=scope)
                return await func(*args, **kwargs)
            key = f"{scope}:{ip}"
            hits = await _increment(key, window_seconds)
            if hits is not None and hits > max_hits:
                log.warning("rate_limit.exceeded", key=key, hits=hits, limit=max_hits)
                raise RateLimitExceeded(retry_after=window_seconds)
            return await func(*args, **kwargs)

        return wrapper

    return decorator
