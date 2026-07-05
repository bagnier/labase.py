"""Fixed-window rate limiting backed by Postgres — multi-instance correct.

Replaces slowapi's in-memory store: with N app instances, each counted alone;
here the hit count is one atomic upsert in a shared table (first
Postgres-as-Redis brick). Fail-open by doctrine: if the store is unreachable
the request goes through and the failure is logged — rate limiting must never
take the product down.
"""

import functools
from collections.abc import Callable
from typing import Any

import structlog
from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared import clock
from apps.shared.config import get_technical_settings
from apps.shared.persistence.database import admin_session_factory

log = structlog.get_logger("labase.shared.limiter")

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
    """Hits for (key, current window) after counting this one; None if the store failed."""
    epoch = int(clock.now().timestamp())
    window_start = epoch - (epoch % window_seconds)
    try:
        async with admin_session_factory()() as session:
            hits = await session.scalar(_INCREMENT, {"key": key, "window_start": window_start})
            await session.commit()
            return int(hits or 0)
    except Exception:
        log.exception("rate_limit.store_failed", key=key)
        return None


async def purge_counters(session: AsyncSession, _payload: dict[str, Any]) -> None:
    """Recurring queue consumer: drop windows old enough to be outside any limit."""
    deleted = await session.scalar(
        text(
            "WITH purged AS ("
            "  DELETE FROM rate_limit_counters"
            "  WHERE window_start < now() - interval '1 day' RETURNING 1"
            ") SELECT count(*) FROM purged"
        )
    )
    log.info("rate_limit.purged", deleted=int(deleted or 0))


def rate_limit(limit_string: str) -> Callable[[Any], Any]:
    """Limit an endpoint per client IP; it must take a `request: Request` parameter."""
    max_hits, window_seconds = _parse(limit_string)

    def decorator(func: Any) -> Any:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            if get_technical_settings().rate_limit_enabled:
                request: Request | None = kwargs.get("request") or next(
                    (a for a in args if isinstance(a, Request)), None
                )
                if request is not None and request.client is not None:
                    key = f"{func.__name__}:{request.client.host}"
                    hits = await _increment(key, window_seconds)
                    if hits is not None and hits > max_hits:
                        log.warning("rate_limit.exceeded", key=key, hits=hits, limit=max_hits)
                        raise RateLimitExceeded(retry_after=window_seconds)
            return await func(*args, **kwargs)

        return wrapper

    return decorator
