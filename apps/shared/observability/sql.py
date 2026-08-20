"""SQL instrumentation — per-query DEBUG logs and a per-request query counter.

Two signals, both request-correlated (``RequestLogger`` binds ``request_id`` in a
contextvar before any handler runs, and SQLAlchemy propagates the context across its
async greenlet boundary):

- ``db.query`` — one DEBUG line per statement with its truncated text and ``duration_ms``.
  Silenced unless the log level is DEBUG (``observability.log_level`` in the console), so
  it costs nothing in production but is one console toggle away — and silenced outright
  inside :func:`without_query_logging`, which the log drain needs so its own INSERT
  does not log a line that the next drain then inserts.
- a per-request tally (:func:`start_request_stats` / :func:`read_request_stats`) folded
  into ``request.finished`` as ``db_queries`` / ``db_ms`` — the always-on signal that
  answers "did this endpoint multiply queries?" without turning on per-query logs.

The tally rides a **mutable** holder in a contextvar (not an int): the listener fires in
SQLAlchemy's greenlet, which gets a *copy* of the request's context — copying shares the
holder object by reference, so in-place mutation there is visible back in the request.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from weakref import WeakSet

import structlog
from sqlalchemy import Engine, event
from sqlalchemy.ext.asyncio import AsyncEngine

log = structlog.get_logger(__name__)

# Sync engines already carrying our listeners — what keeps ``instrument_engine`` idempotent without
# stamping an attribute onto SQLAlchemy's ``Engine``. Weak, so a disposed engine can be collected.
_instrumented: WeakSet[Engine] = WeakSet()

_MAX_STATEMENT = 300  # statements are truncated in logs; full text lives in Postgres


@dataclass
class QueryStats:
    """Per-request accumulator, mutated in place from the execute listener."""

    count: int = 0
    total_ms: float = 0.0


_stats: ContextVar[QueryStats | None] = ContextVar("db_query_stats", default=None)

# Set while a caller is running statements whose own ``db.query`` line must not be written.
# Read from the listener's greenlet, which gets a *copy* of the context: a value bound before
# entering travels with the copy, which is all this needs (unlike the stats holder, which is
# mutated from there and so has to be an object shared by reference).
_muted: ContextVar[bool] = ContextVar("db_query_muted", default=False)


@contextmanager
def without_query_logging() -> Iterator[None]:
    """Silence ``db.query`` for the statements run inside.

    One caller needs this, and needs it absolutely: the log drain. Its INSERT is a statement
    like any other, so at DEBUG level it logs a line — which is enqueued, inserted by the next
    drain, and logs another. Not a burst but a floor: the queue would never reach empty again, and
    the store would fill with the record of its own writes.
    """
    token = _muted.set(True)
    try:
        yield
    finally:
        _muted.reset(token)


def start_request_stats() -> None:
    """Begin a fresh tally for the current request (called by ``RequestLogger``)."""
    _stats.set(QueryStats())


def read_request_stats() -> QueryStats | None:
    """The current request's tally, or ``None`` outside an instrumented request."""
    return _stats.get()


def _squash(statement: str) -> str:
    return " ".join(statement.split())[:_MAX_STATEMENT]


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
            stats.count += 1
            stats.total_ms += elapsed_ms
        # Counted even when muted: the tally is what ``request.finished`` reports, and a muted
        # statement is still a query the request paid for.
        if not _muted.get():
            log.debug("db.query", statement=_squash(statement), duration_ms=elapsed_ms)
