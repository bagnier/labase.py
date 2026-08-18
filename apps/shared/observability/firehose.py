"""The structlog firehose, persisted as per-day JSON lines beside stdout.

12-factor: logs are a stream, so every event is still rendered to stdout. In addition, this
module appends each event as one JSON object to a per-day file under the firehose directory,
giving the unified timeline viewer (``apps/timeline``) a recent window to read back. Nothing goes to
the app DB — the files *are* the ``request`` source of truth, and per-day rotation makes
retention a plain file delete.

The firehose only backs a *recent* window in the viewer (:data:`FIREHOSE_WINDOW`); older days
stay on disk for export and retention but drop out of the live timeline.

**Non-blocking by doctrine.** The runtime log path never touches the disk: the structlog
processor only *enqueues* the record (a plain :meth:`deque.append`, atomic under the GIL — safe
before the event loop exists and from worker threads, exactly like the capture queue), and a
background :class:`FirehoseWriter` lifespan task batches the queue to the day files. Tests and
seeds still call :func:`append_firehose` directly for a synchronous write they can read back at
once; that low-level writer is also what the background drain uses.
"""

import asyncio
import contextlib
import json
from collections import defaultdict, deque
from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import structlog

from apps.shared import clock
from apps.shared.config import get_technical_settings

FIREHOSE_WINDOW = timedelta(days=2)

# Event-dict keys promoted to first-class columns; everything else lands in ``payload``.
_RESERVED = {"timestamp", "level", "event", "org_id", "user_id", "request_id"}


@dataclass(frozen=True)
class LogLine:
    """One firehose line, flattened for the unified timeline."""

    ts: datetime
    level: str
    event: str
    org_id: str | None
    user_id: str | None
    request_id: str | None
    payload: dict[str, Any]


def firehose_dir() -> Path:
    path = Path(get_technical_settings().firehose_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _file_for(ts: datetime) -> Path:
    return firehose_dir() / f"firehose-{ts.date().isoformat()}.jsonl"


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str):
        ts = datetime.fromisoformat(value)
    else:
        ts = clock.now()
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def append_firehose(record: dict[str, Any]) -> None:
    """Append one event as a JSON line to its day's file. Best-effort: a firehose write must
    never break the request that logged it (matches the business-event/metrics doctrine).

    The synchronous, low-level writer: tests and seeds call it directly for a line they read back
    at once, and the background :class:`FirehoseWriter` funnels the runtime queue through it."""
    _write_batch(_file_for(_parse_ts(record.get("timestamp"))), [record])


def _write_batch(path: Path, records: list[dict[str, Any]]) -> None:
    """Append several records to one day's file in a single ``open`` — the drain's unit of work."""
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.writelines(json.dumps(r, default=str) + "\n" for r in records)
    except OSError:
        pass


# Where runtime log lines wait, between the structlog processor (producer) and the background writer
# (consumer). Bounded so that with no writer draining — disabled, or a unit run that logs but never
# starts the lifespan task — the queue self-caps by dropping the oldest line instead of growing
# without limit. The firehose is a best-effort tail, never load-bearing.
_QUEUE: deque[dict[str, Any]] = deque(maxlen=10000)


def enqueue_firehose(record: dict[str, Any]) -> None:
    """Hand one record to the writer queue — a plain ``deque.append``, no I/O and no await, so it
    is safe on the request's critical path, before the loop exists, and from worker threads."""
    _QUEUE.append(record)


def firehose_processor(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: enqueue the (level-filtered) event for the firehose, pass it through.

    Runs after ``TimeStamper``/``add_log_level``/``merge_contextvars`` so the record carries
    its timestamp, level and correlation ids; sits before the renderer so it sees a plain dict.
    Enqueue only — the disk write happens off the request path in :class:`FirehoseWriter`. A
    snapshot (``dict(event_dict)``) is queued because later processors mutate the live mapping.
    Below-level calls are dropped by the filtering wrapper before any processor runs, so the
    firehose is naturally gated by the live log level.
    """
    enqueue_firehose(dict(event_dict))
    return event_dict


def _line(record: dict[str, Any]) -> LogLine:
    return LogLine(
        ts=_parse_ts(record.get("timestamp")),
        level=str(record.get("level") or "info"),
        event=str(record.get("event") or ""),
        org_id=record.get("org_id"),
        user_id=record.get("user_id"),
        request_id=record.get("request_id"),
        payload={k: v for k, v in record.items() if k not in _RESERVED},
    )


def _recent_files(floor: datetime) -> list[Path]:
    files = []
    for path in firehose_dir().glob("firehose-*.jsonl"):
        try:
            day = datetime.fromisoformat(path.stem.removeprefix("firehose-")).date()
        except ValueError:
            continue
        if day >= floor.date():
            files.append(path)
    return files


def read_firehose(
    *,
    level: str | None = None,
    org_id: str | None = None,
    user_id: str | None = None,
    request_id: str | None = None,
    text: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    window: timedelta = FIREHOSE_WINDOW,
    limit: int = 100,
) -> list[LogLine]:
    """Newest-first read of the firehose over its recent window, under the given filters.

    The window floor (``now - window``) is the firehose's own retention horizon; an explicit
    ``from_dt`` can only tighten it, never reach further back than the window keeps."""
    floor = clock.now() - window
    if from_dt and from_dt > floor:
        floor = from_dt
    needle = text.lower() if text else None
    lines: list[LogLine] = []
    for path in _recent_files(floor):
        for raw in path.read_text(encoding="utf-8").splitlines():
            serialized = raw.strip()
            if not serialized:
                continue
            try:
                line = _line(json.loads(serialized))
            except json.JSONDecodeError:
                continue
            if line.ts < floor or (to_dt and line.ts > to_dt):
                continue
            if level and line.level.lower() != level.lower():
                continue
            if org_id and line.org_id != org_id:
                continue
            if user_id and line.user_id != user_id:
                continue
            if request_id and line.request_id != request_id:
                continue
            if needle and needle not in serialized.lower():
                continue
            lines.append(line)
    lines.sort(key=lambda entry: entry.ts, reverse=True)
    return lines[:limit]


def clear_firehose() -> None:
    """Drop queued lines and delete every firehose file — test isolation between scenarios."""
    _QUEUE.clear()
    for path in firehose_dir().glob("firehose-*.jsonl"):
        path.unlink(missing_ok=True)


class FirehoseWriter:
    """Lifespan task that drains the log queue to the per-day files off the request path.

    Same shape as ``MetricsFlusher``/``CaptureDrain`` — idempotent ``start``, cancel-and-await
    ``stop`` (with a final drain so a graceful shutdown loses no buffered line), and a ``tick``
    tests can drive by hand. Each tick groups the queued records by their day file so a burst of
    lines costs one ``open`` per file, not one per line."""

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
        self.tick()  # flush whatever the cancelled loop left behind

    def tick(self) -> None:
        # Snapshot the current length so lines appended mid-drain wait for the next tick.
        batches: dict[Path, list[dict[str, Any]]] = defaultdict(list)
        for _ in range(len(_QUEUE)):
            try:
                record = _QUEUE.popleft()
            except IndexError:
                break
            batches[_file_for(_parse_ts(record.get("timestamp")))].append(record)
        for path, records in batches.items():
            _write_batch(path, records)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                self.tick()
            except Exception:
                # A drain failure is degraded-but-manageable; warn (never log.exception, which the
                # firehose would re-enqueue) and retry next tick with the lines still queued.
                structlog.get_logger("labase.firehose").warning("firehose.drain_failed")
