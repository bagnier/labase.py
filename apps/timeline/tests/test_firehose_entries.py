"""How a firehose line lands in the timeline.

The timeline merges three sources — the business-events journal, the logs, and issue
occurrences. The logs are *one* source: a request trace and a background failure differ by
their name and their level, not by where they come from. What the line does carry is its
app, read off the logger that wrote it.
"""

from datetime import UTC, datetime

import pytest

from apps.shared import clock
from apps.shared.config import get_technical_settings
from apps.shared.observability import firehose
from apps.shared.observability.firehose import append_firehose
from apps.timeline.domain.models import TimelineSource
from apps.timeline.infra.repository import TimelineFilter

# The firehose reads a window around ``clock.now()``; pinning both ends keeps it deterministic.
_NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
_THEN = "2026-07-12T10:00:00"


@pytest.fixture(autouse=True)
def _isolate_firehose(tmp_path, monkeypatch):
    settings = get_technical_settings()
    monkeypatch.setattr(settings, "firehose_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(firehose, "get_technical_settings", lambda: settings)
    monkeypatch.setattr(clock, "now", lambda: _NOW)
    firehose.clear_firehose()
    yield
    firehose.clear_firehose()


def _seed(logger: str, event: str) -> None:
    append_firehose({"timestamp": _THEN, "level": "error", "logger": logger, "event": event})


def _shown(entries) -> list[tuple[TimelineSource, str, str]]:
    return [(e.source, e.app, e.name) for e in entries]


@pytest.mark.asyncio
async def test_a_request_trace_is_a_log_like_any_other(reader):
    _seed("apps.shared.observability.request", "request.finished")
    entries = await reader.search(TimelineFilter(source="logs"))
    assert _shown(entries) == [(TimelineSource.logs, "shared", "request.finished")]


@pytest.mark.asyncio
async def test_a_background_failure_is_a_log_like_any_other(reader):
    _seed("apps.shared.queue", "queue.task_failed")
    entries = await reader.search(TimelineFilter(source="logs"))
    assert _shown(entries) == [(TimelineSource.logs, "shared", "queue.task_failed")]


@pytest.mark.asyncio
async def test_a_library_line_names_its_app_after_the_library(reader):
    """A third-party logger has no package under ``apps/``: it names itself."""
    _seed("sqlalchemy.pool", "connection invalidated")
    entries = await reader.search(TimelineFilter(source="logs"))
    assert _shown(entries) == [(TimelineSource.logs, "sqlalchemy", "connection invalidated")]
