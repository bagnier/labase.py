"""The structlog firehose, persisted as per-day JSON lines beside stdout.

12-factor: logs are a stream, so every event is still rendered to stdout. In addition, this
module appends each event as one JSON object to a per-day file under the firehose directory,
giving the unified logs viewer (``apps/logs``) a recent window to read back. Nothing goes to
the app DB — the files *are* the ``request`` source of truth, and per-day rotation makes
retention a plain file delete.

The firehose only backs a *recent* window in the viewer (:data:`FIREHOSE_WINDOW`); older days
stay on disk for export and retention but drop out of the live timeline.
"""

import json
from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from apps.shared import clock
from apps.shared.config import get_technical_settings

FIREHOSE_WINDOW = timedelta(days=2)

# Event-dict keys promoted to first-class columns; everything else lands in ``payload``.
_RESERVED = {"timestamp", "level", "event", "org_id", "user_id", "request_id"}


@dataclass(frozen=True)
class FirehoseRow:
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
    never break the request that logged it (matches the audit/metrics doctrine)."""
    when = _parse_ts(record.get("timestamp"))
    line = json.dumps(record, default=str)
    try:
        with _file_for(when).open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def firehose_processor(
    _logger: Any, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: tee the (level-filtered) event to the firehose, pass it through.

    Runs after ``TimeStamper``/``add_log_level``/``merge_contextvars`` so the record carries
    its timestamp, level and correlation ids; sits before the renderer so it sees a plain dict.
    Below-level calls are dropped by the filtering wrapper before any processor runs, so the
    firehose is naturally gated by the live log level.
    """
    append_firehose(dict(event_dict))
    return event_dict


def _row(record: dict[str, Any]) -> FirehoseRow:
    return FirehoseRow(
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
) -> list[FirehoseRow]:
    """Newest-first read of the firehose over its recent window, under the given filters.

    The window floor (``now - window``) is the firehose's own retention horizon; an explicit
    ``from_dt`` can only tighten it, never reach further back than the window keeps."""
    floor = clock.now() - window
    if from_dt and from_dt > floor:
        floor = from_dt
    needle = text.lower() if text else None
    rows: list[FirehoseRow] = []
    for path in _recent_files(floor):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = _row(json.loads(line))
            except json.JSONDecodeError:
                continue
            if row.ts < floor or (to_dt and row.ts > to_dt):
                continue
            if level and row.level.lower() != level.lower():
                continue
            if org_id and row.org_id != org_id:
                continue
            if user_id and row.user_id != user_id:
                continue
            if request_id and row.request_id != request_id:
                continue
            if needle and needle not in line.lower():
                continue
            rows.append(row)
    rows.sort(key=lambda r: r.ts, reverse=True)
    return rows[:limit]


def clear_firehose() -> None:
    """Delete every firehose file — test isolation between scenarios."""
    for path in firehose_dir().glob("firehose-*.jsonl"):
        path.unlink(missing_ok=True)
