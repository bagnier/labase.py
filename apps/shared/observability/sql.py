"""SQL instrumentation — what a request spent in the database, and when that is a surprise.

One accumulator, request-correlated (``RequestLogger`` binds ``request_id`` in a contextvar
before any handler runs, and SQLAlchemy propagates the context across its async greenlet
boundary), read by two surfaces:

- ``request.finished`` carries ``db_queries`` / ``db_ms`` — the always-on answer to "what did
  this exchange cost", stated once, on the line that already exists.
- :func:`report_heavy_request` writes ``db.heavy_request`` when either threshold is crossed,
  naming the statements that cost the time. This is the whole of what a per-statement ``debug``
  firehose used to buy, minus the line-per-query on every healthy request — and it needs no
  muting machinery, because it writes at most one line *after* the statements have run rather
  than one line *inside* each of them (the log drain's own INSERT used to feed the very queue it
  had just failed to empty).

The tally rides a **mutable** holder in a contextvar (not an int): the listener fires in
SQLAlchemy's greenlet, which gets a *copy* of the request's context — copying shares the
holder object by reference, so in-place mutation there is visible back in the request.
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

# Sync engines already carrying our listeners — what keeps ``instrument_engine`` idempotent without
# stamping an attribute onto SQLAlchemy's ``Engine``. Weak, so a disposed engine can be collected.
_instrumented: WeakSet[Engine] = WeakSet()

_MAX_STATEMENT = 300  # statements are truncated in logs; full text lives in Postgres


# How many statements a heavy request names. What a reader opens the line for is the handful that
# cost the time, never the ten thousand a runaway loop ran.
_KEPT_STATEMENTS = 5

# When a request's SQL becomes the surprise. Either threshold is enough: one slow statement and
# forty quick ones are both worth a line, and neither implies the other. Overridden live by
# ``apps/timeline`` from its settings, the way ``apply_log_level`` already is.
DEFAULT_HEAVY_QUERIES = 30
DEFAULT_HEAVY_MS = 500


@dataclass
class _HeavyRequest:
    queries: int = DEFAULT_HEAVY_QUERIES
    ms: float = DEFAULT_HEAVY_MS


_heavy = _HeavyRequest()


def apply_heavy_request_thresholds(*, queries: int, ms: float) -> None:
    """Re-point the thresholds — the twin of ``apply_log_level``, and pushed the same way.

    ``apps/shared`` may not read a context's settings by name (a foundation naming a feature), so
    ``apps/timeline`` calls this at mount and again on every ``SettingsChanged``.
    """
    _heavy.queries, _heavy.ms = queries, ms


@dataclass
class QueryStats:
    """Per-request accumulator, mutated in place from the execute listener.

    ``slowest`` keeps the statements themselves, bounded: a reference each, squashed only if the
    request turns out to be heavy — so a normal request pays a comparison and no string work.
    """

    count: int = 0
    total_ms: float = 0.0
    slowest: list[tuple[float, str]] = field(default_factory=list)

    def remember(self, statement: str, ms: float) -> None:
        """Fold one statement into the tally, keeping it only while it is among the slowest."""
        self.count += 1
        self.total_ms += ms
        self.slowest.append((ms, statement))
        if len(self.slowest) > _KEPT_STATEMENTS:
            self.slowest.remove(min(self.slowest))

    def is_heavy(self) -> bool:
        return self.count >= _heavy.queries or self.total_ms >= _heavy.ms


_stats: ContextVar[QueryStats | None] = ContextVar("db_query_stats", default=None)


def start_request_stats() -> None:
    """Begin a fresh tally for the current request (called by ``RequestLogger``)."""
    _stats.set(QueryStats())


def read_request_stats() -> QueryStats | None:
    """The current request's tally, or ``None`` outside an instrumented request."""
    return _stats.get()


def _squash(statement: str) -> str:
    return " ".join(statement.split())[:_MAX_STATEMENT]


def report_heavy_request() -> None:
    """Say that this request's SQL was the surprise, and name the statements that made it so.

    Carries neither path nor method nor status: ``request.finished`` states those once, and both
    lines already share the ``request_id`` the timeline correlates on. What is here is what
    nothing else holds — which statements cost the time.

    Silent outside a request, since nothing opened a tally: background work is answered by the
    task queue's own row, not by this line.
    """
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
    """Attach execute listeners to ``engine`` (idempotent per engine).

    Listens on the underlying sync engine — that's where the DBAPI cursor events fire.
    """
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
