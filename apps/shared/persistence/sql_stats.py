"""What a request spent in the database: ``db_queries``/``db_ms`` on ``request.finished``, and a
``db.heavy_request`` line naming the slowest statements when a threshold is crossed.

The tally is a mutable holder in a contextvar: SQLAlchemy's listener runs in a greenlet holding a
copy of the request's context, and the copy shares the holder.
"""

from __future__ import annotations

import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from weakref import WeakSet

import structlog
from sqlalchemy import Engine, event
from sqlalchemy.ext.asyncio import AsyncEngine

log = structlog.get_logger(__name__)

# Engines already instrumented; weak, so a disposed engine can be collected.
_instrumented: WeakSet[Engine] = WeakSet()

_MAX_STATEMENT = 300

# How many of the slowest statements a heavy request names.
_KEPT_STATEMENTS = 5

# Either threshold makes a request heavy. ``apps/timeline`` overrides them from its settings.
DEFAULT_HEAVY_QUERIES = 30
DEFAULT_HEAVY_MS = 500


@dataclass
class _HeavyRequest:
    queries: int = DEFAULT_HEAVY_QUERIES
    ms: float = DEFAULT_HEAVY_MS


_heavy = _HeavyRequest()


def apply_heavy_request_thresholds(*, queries: int, ms: float) -> None:
    """Called by ``apps/timeline`` at mount and on ``SettingsChanged``: shared cannot read a
    context's settings."""
    _heavy.queries, _heavy.ms = queries, ms


@dataclass
class QueryStats:
    """Per-request tally. ``slowest`` keeps raw statements, formatted only if the request turns
    out heavy."""

    count: int = 0
    total_ms: float = 0.0
    slowest: list[tuple[float, str]] = field(default_factory=list)

    def remember(self, statement: str, ms: float) -> None:
        self.count += 1
        self.total_ms += ms
        self.slowest.append((ms, statement))
        if len(self.slowest) > _KEPT_STATEMENTS:
            self.slowest.remove(min(self.slowest))

    def is_heavy(self) -> bool:
        return self.count >= _heavy.queries or self.total_ms >= _heavy.ms


_stats: ContextVar[QueryStats | None] = ContextVar("db_query_stats", default=None)


def start_request_stats() -> None:
    _stats.set(QueryStats())


def read_request_stats() -> QueryStats | None:
    """``None`` outside an instrumented request."""
    return _stats.get()


def _squash(statement: str) -> str:
    return " ".join(statement.split())[:_MAX_STATEMENT]


def report_heavy_request() -> None:
    """Log ``db.heavy_request`` if this request crossed a threshold. Path and status are on
    ``request.finished``, joined by ``request_id``."""
    stats = _stats.get()
    if stats is None or not stats.is_heavy():
        return
    log.info(
        "db.heavy_request",
        db_queries=stats.count,
        db_ms=round(stats.total_ms, 1),
        slowest=[
            {"ms": ms, "statement": _squash(statement)}
            for ms, statement in sorted(stats.slowest, reverse=True)
        ],
    )


def instrument_engine(engine: AsyncEngine) -> None:
    """Attach the timing listeners, once per engine, on its sync engine where cursor events
    fire."""
    sync_engine = engine.sync_engine
    if sync_engine in _instrumented:
        return
    _instrumented.add(sync_engine)

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("_labase_query_start", []).append(time.perf_counter())

    @event.listens_for(sync_engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        starts = conn.info.get("_labase_query_start")
        elapsed_ms = round((time.perf_counter() - starts.pop()) * 1000, 2) if starts else 0.0
        stats = _stats.get()
        if stats is not None:
            stats.remember(statement, elapsed_ms)
