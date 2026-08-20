"""The log sink — everything that carries a technical line from the code to where it is kept.

A *sink* is what dedicated tooling (Serilog, Vector, OpenTelemetry) calls a log destination, and
what it means there is the whole write-side apparatus: the entry point, the buffering, the retry
and the fallback — not the storage itself. Here that is the structlog processor, the bounded queue
between the request path and the writer, the background :class:`LogDrain`, and the day files.

The storage is :mod:`apps.shared.observability.repository`, whose ``LogRepository`` owns the SQL
against ``log_lines`` — the house word for "the object that holds a table's queries", and the twin
of ``EventRepository`` on the journal side.

12-factor: every line is still rendered to stdout, which is what an aggregator reads. In addition
each one is appended to ``log_lines``, giving the console Timeline a queryable window it can
filter, correlate and page over alongside the journal and the issues.

**Why a table.** This used to be per-day JSON Lines on local disk. With one instance that reads
fine; with two it makes the Timeline lie by omission — the journal and the issues are in Postgres
and therefore global, so an admin correlating a request saw the fact and the occurrence and missed
every line between them, depending on which instance answered the page. Retention had the mirror
problem: per-day rotation was supposed to make it "a plain file delete", and nothing ever deleted.

**The two words.** A *sink* is where log lines land — the term dedicated tooling uses (Serilog,
Vector, OpenTelemetry). A *drain* here is what this codebase already means by it: a lifespan task
that empties a bounded queue into whoever consumes it, exactly like ``CaptureDrain``. Not Heroku's
sense of the word, and internal consistency wins — the shape is already familiar.

**The files survive, as the fallback.** When the sink itself is what is down, a batch Postgres
refuses is written to its day file instead: a database outage is precisely when an operator still
wants to read the log. The dying-process hook writes there too — it runs during interpreter
shutdown, with no loop and no pool left to await on.

**Non-blocking by doctrine.** The runtime log path touches neither disk nor database: the structlog
processor only *enqueues* the line (a plain :meth:`deque.append`, atomic under the GIL — safe
before the event loop exists and from worker threads, exactly like the capture queue), and the
background :class:`LogDrain` batches the queue to the sink.
"""

import asyncio
import contextlib
import json
from collections import defaultdict, deque
from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from apps.shared import clock
from apps.shared.config import get_technical_settings
from apps.shared.observability.repository import LogRepository
from apps.shared.persistence.database import admin_session_factory

log = structlog.get_logger(__name__)


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str):
        ts = datetime.fromisoformat(value)
    else:
        ts = clock.now()
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


# ── The sink ─────────────────────────────────────────────────────────────────────────────────


# ── The fallback: per-day files, for when the store is what is down ──────────────────────────


@dataclass
class _Outage:
    """Whether the *store* is refusing lines, and how many it has refused since it last took one.

    The store, not the files: the files are where a refused batch goes, so their success is not
    news — what an operator needs told is that the Timeline has stopped seeing new lines.

    Reported on its two *transitions* and silent in between, for the reason the capture queue
    counts its overflow rather than logging it: the report is itself a log line, so one per refused
    write would feed the very queue that cannot be drained. Stdout still works during an outage, so
    the entry line reaches an aggregator immediately even while the store cannot take it; the exit
    line carries the toll, which is only final once the store accepts again.
    """

    lines: int = 0
    refusing: bool = False
    announced: bool = False


_outage = _Outage()


@dataclass
class _Overflow:
    """How many lines the bounded queue shed before any drain could take them — the twin of the
    capture queue's counter, and for the same reason: a dropped line is one the Timeline will
    never show, and silence there reads exactly like a quiet server.

    Counted rather than logged where it happens: the shedding happens inside
    :func:`enqueue_line`, on the log path itself, so a line of its own would feed the very queue
    that is already full. The drain says it instead, once per tick.
    """

    dropped: int = 0


_overflow = _Overflow()


def fallback_dir() -> Path:
    """Where a batch goes when the store refuses it.

    Still read from ``FIREHOSE_DIR``: the env var is deployment-visible and documented
    (docs/production.md), so it outlives the code's own vocabulary rather than breaking a running
    deploy for a name.
    """
    path = Path(get_technical_settings().firehose_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _file_for(ts: datetime) -> Path:
    return fallback_dir() / f"firehose-{ts.date().isoformat()}.jsonl"


def _write_batch(path: Path, lines: list[dict[str, Any]]) -> bool:
    """Append several lines to one day's file in a single ``open``. Returns whether they landed.

    Best-effort by doctrine: neither the store nor this fallback may break the request that logged
    the line. What was refused is tallied on :data:`_outage`.
    """
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.writelines(json.dumps(one, default=str) + "\n" for one in lines)
    except OSError:
        return False
    return True


def append_to_file(line: dict[str, Any]) -> None:
    """Append one line to its day file — the low-level synchronous fallback writer."""
    _write_to_files([line])


def _write_to_files(lines: list[dict[str, Any]]) -> None:
    """Send a batch to the day files, grouped so a burst spanning midnight costs two ``open``s
    rather than one per line.

    The fallback of a fallback: if the disk refuses too there is nowhere left to put the line, and
    saying so would mean writing one. It stays silent by design — stdout already carried it."""
    batches: dict[Path, list[dict[str, Any]]] = defaultdict(list)
    for line in lines:
        batches[_file_for(_parse_ts(line.get("timestamp")))].append(line)
    for path, batch in batches.items():
        _write_batch(path, batch)


def report_overflow() -> None:
    """Say what the queue shed since the last tick — once per tick, never once per lost line."""
    dropped, _overflow.dropped = _overflow.dropped, 0
    if dropped:
        log.warning("log_sink.overflowed", dropped=dropped)


def report_write_outage() -> None:
    """Say that the store stopped accepting lines, or started again — once per transition."""
    if _outage.refusing and not _outage.announced:
        _outage.announced = True
        log.error("log_sink.write_failed")
    elif not _outage.refusing and _outage.announced:
        _outage.announced = False
        log.info("log_sink.write_recovered", lines=_outage.lines)
        _outage.lines = 0


# ── The queue between the log path and the writer ────────────────────────────────────────────

# Bounded so that with no writer draining — a unit run that logs but never starts the lifespan
# task — the queue self-caps by dropping the oldest line instead of growing without limit. The
# sink is a best-effort tail, never load-bearing.
_QUEUE: deque[dict[str, Any]] = deque(maxlen=10000)


def enqueue_line(line: dict[str, Any]) -> None:
    """Hand one line to the writer queue — a plain ``deque.append``, no I/O and no await, so it is
    safe on the request's critical path, before the loop exists, and from worker threads.

    A full queue displaces its oldest line; that one is tallied here and reported by the drain.
    """
    if len(_QUEUE) == _QUEUE.maxlen:
        _overflow.dropped += 1
    _QUEUE.append(line)


def log_processor(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: enqueue the line for the sink, pass it through.

    Sits in the terminal chain (see :mod:`apps.shared.observability.logging`), after the shared
    processors have given the line its timestamp, level, logger and correlation ids, and before the
    renderer — so it sees a plain dict, whoever wrote it. Enqueue only: the write happens off the
    request path in :class:`FirehoseWriter`. A snapshot (``dict(event_dict)``) is queued because
    the renderer mutates the live mapping. Below-level calls never reach here, so the sink is
    gated by the live log level without testing it.
    """
    enqueue_line(dict(event_dict))
    return event_dict


def _drain_queue() -> list[dict[str, Any]]:
    """Take what is queued *now*. Snapshotting the length first means a line appended mid-drain
    simply waits for the next one, rather than extending this pass indefinitely."""
    taken = []
    for _ in range(len(_QUEUE)):
        try:
            taken.append(_QUEUE.popleft())
        except IndexError:
            break
    return taken


def flush_to_files() -> None:
    """Write everything queued to the day files, now, on the calling thread.

    The only way out for a line nobody will be around to drain — the last one a dying process
    logs, written from the interpreter's exit hook where there is no loop and no pool left.
    """
    _write_to_files(_drain_queue())


def clear_log_sink() -> None:
    """Drop queued lines and delete every fallback file — test isolation between scenarios."""
    _QUEUE.clear()
    _outage.lines, _outage.refusing, _outage.announced = 0, False, False
    _overflow.dropped = 0
    for path in fallback_dir().glob("firehose-*.jsonl"):
        path.unlink(missing_ok=True)


class LogDrain:
    """Lifespan task that drains the log queue to the store, off the request path.

    Same shape as ``MetricsFlusher``/``CaptureDrain`` — idempotent ``start``, cancel-and-await
    ``stop`` (with a final drain so a graceful shutdown loses no buffered line), and a ``tick``
    tests can drive by hand.
    """

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
        await self.tick()  # flush whatever the cancelled loop left behind

    async def tick(self) -> None:
        """Drain once: to the store, and to the day files if the store refuses."""
        lines = _drain_queue()
        if lines:
            try:
                async with admin_session_factory()() as session:
                    await LogRepository(session).append(lines)
                    await session.commit()
            except Exception:
                # No ``log.exception`` and no verdict here: the store being down is already said by
                # ``report_write_outage``, once per transition, and an exception at this point
                # would be one more line feeding the queue that cannot be drained.
                _outage.refusing = True
                _outage.lines += len(lines)
                _write_to_files(lines)
            else:
                _outage.refusing = False
            report_write_outage()
        # Outside the guard above: what the queue shed is owed whether or not this pass had
        # anything left to write.
        report_overflow()

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.tick()
            except Exception as exc:
                # A drain failure is degraded-but-manageable; warn (never ``log.exception``, which
                # the sink would re-enqueue) and retry next tick with the lines still queued.
                log.warning("log_sink.drain_failed", exc_info=exc)
