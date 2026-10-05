"""The log sink: carries each line from the chain to ``log_lines``
(AGENTS: the log sink traces the machinery off the request's path).

:func:`log_processor` only appends to a bounded deque, safe before the event loop exists and from
worker threads. :class:`LogDrain` writes batches through :mod:`apps.shared.logs.repository`, and
to per-day files when Postgres refuses them. The dying-process hook writes to those files too.
"""

import asyncio
import contextlib
import json
import logging
import math
from collections import defaultdict, deque
from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from apps.shared import clock
from apps.shared.logs.repository import LogRepository
from apps.shared.persistence.database import admin_session_factory
from apps.shared.settings.env import get_technical_settings

log = structlog.get_logger(__name__)

# The sink's reports on itself (outage, recovery, overflow) must reach the Timeline whatever
# level an admin set, so ``_log`` is built outside ``structlog.configure()`` and its stdlib logger
# pinned to INFO: ``apply_log_level`` re-points both. The processors copy ``chain.py``'s, which
# imports this module.
logging.getLogger(__name__).setLevel(logging.INFO)
_log = structlog.wrap_logger(
    logging.getLogger(__name__),
    wrapper_class=structlog.stdlib.BoundLogger,
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
)


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str):
        ts = datetime.fromisoformat(value)
    else:
        ts = clock.now()
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


# ── The fallback: per-day files, for when the store is what is down ──────────────────────────


@dataclass
class _Outage:
    """Whether the store refuses lines, and how many it refused since it last took one.

    Reported on its two transitions only: each report is itself a line for the queue that cannot
    drain. The recovery line carries the count.
    """

    lines: int = 0
    refusing: bool = False
    announced: bool = False


_outage = _Outage()


@dataclass
class _Overflow:
    """Lines the full queue dropped. Reported by the drain: logging from :func:`enqueue_line`
    would feed the full queue."""

    dropped: int = 0


_overflow = _Overflow()


def fallback_dir() -> Path:
    """The day files' directory, ``FIREHOSE_DIR`` (named in docs/production.md)."""
    path = Path(get_technical_settings().firehose_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_batch(path: Path, lines: list[dict[str, Any]]) -> bool:
    """Append lines to one day's file; returns whether they landed."""
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.writelines(json.dumps(one, default=str) + "\n" for one in lines)
    except OSError:
        return False
    return True


def append_to_file(line: dict[str, Any]) -> None:
    _write_to_files([line])


def _write_to_files(lines: list[dict[str, Any]]) -> None:
    """One ``open`` per day file. Silent if the disk refuses too: stdout already has the lines."""
    base = fallback_dir()
    batches: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    for line in lines:
        ts = _parse_ts(line.get("timestamp"))
        batches[base / f"firehose-{ts.date().isoformat()}.jsonl"].append(line)
    for path, batch in batches.items():
        _write_batch(path, batch)


def report_overflow() -> None:
    """Report what the queue dropped since the last tick."""
    dropped, _overflow.dropped = _overflow.dropped, 0
    if dropped:
        _log.warning("log_sink.overflowed", dropped=dropped)


def report_write_outage() -> None:
    if _outage.refusing and not _outage.announced:
        _outage.announced = True
        # A warning: absorbed, the batch went to the day files.
        _log.warning("log_sink.write_failed")
    elif not _outage.refusing and _outage.announced:
        _outage.announced = False
        _log.info("log_sink.write_recovered", lines=_outage.lines)
        _outage.lines = 0


# ── The queue between the log path and the writer ────────────────────────────────────────────

# Bounded: with no drain running (a unit test), the oldest lines are dropped.
_QUEUE: deque[dict[str, Any]] = deque(maxlen=10000)


def enqueue_line(line: dict[str, Any]) -> None:
    """Queue one line, no I/O; a full queue drops its oldest."""
    if len(_QUEUE) == _QUEUE.maxlen:
        _overflow.dropped += 1
    _QUEUE.append(line)


def log_processor(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Queue a copy of the line (the renderer mutates it) and pass it on. Lines below the live
    level never get here."""
    enqueue_line(dict(event_dict))
    return event_dict


def _drain_queue() -> list[dict[str, Any]]:
    """Take what is queued now; lines appended meanwhile wait for the next pass."""
    taken = []
    for _ in range(len(_QUEUE)):
        try:
            taken.append(_QUEUE.popleft())
        except IndexError:
            break
    return taken


def flush_to_files() -> None:
    """Write the queue to the day files, synchronously: for the exit hook of a dying process."""
    _write_to_files(_drain_queue())


def clear_log_sink() -> None:
    """Reset the queue, counters and day files between test scenarios."""
    _QUEUE.clear()
    _outage.lines, _outage.refusing, _outage.announced = 0, False, False
    _overflow.dropped = 0
    for path in fallback_dir().glob("firehose-*.jsonl"):
        path.unlink(missing_ok=True)


class LogDrain:
    """Lifespan task draining the queue to the store; ``stop`` drains once more."""

    def __init__(self, interval_seconds: float) -> None:
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._interval > 0 and self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self.tick()

    async def tick(self) -> None:
        lines = _drain_queue()
        if lines:
            try:
                lock_timeout_ms = math.ceil(
                    get_technical_settings().log_drain_lock_timeout_seconds * 1000
                )
                async with admin_session_factory()() as session:
                    await LogRepository(session).append(lines, lock_timeout_ms=lock_timeout_ms)
                    await session.commit()
            except Exception:
                # Not logged here: ``report_write_outage`` says it once per transition.
                _outage.refusing = True
                _outage.lines += len(lines)
                # Blocking file I/O, off the event loop.
                await asyncio.to_thread(_write_to_files, lines)
            else:
                _outage.refusing = False
            report_write_outage()
        report_overflow()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.tick()
            except Exception as exc:
                # Not log.exception, which the sink would queue again; retried next tick.
                log.warning("log_sink.drain_failed", exc_info=exc)
