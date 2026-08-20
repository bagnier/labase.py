"""How a log line lands in the timeline.

The timeline merges three sources — the business-events journal, the logs, and issue
occurrences. The logs are *one* source: a request trace and a background failure differ by
their name and their level, not by where they come from. What the line does carry is its
app, read off the logger that wrote it.
"""

from datetime import UTC, datetime

import pytest
import pytest_asyncio

from apps.shared import clock
from apps.shared.config import get_technical_settings
from apps.shared.observability import sink
from apps.shared.tests.log_seed import clear_log_lines, seed_log_line
from apps.timeline.domain.models import TimelineSource
from apps.timeline.infra.repository import TimelineFilter

# The sink reads a window around ``clock.now()``; pinning both ends keeps it deterministic.
_NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
_THEN = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _pin_the_clock(tmp_path, monkeypatch):
    settings = get_technical_settings()
    monkeypatch.setattr(settings, "firehose_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(sink, "get_technical_settings", lambda: settings)
    monkeypatch.setattr(clock, "now", lambda: _NOW)


@pytest_asyncio.fixture(autouse=True)
async def _only_my_lines(reader):
    """The store is shared and committed — the day files this replaced gave each test a scratch
    directory. These tests assert over *every* ``logs`` entry, so they start from empty."""
    await clear_log_lines(reader.session)
    yield
    await clear_log_lines(reader.session)


async def _seed(reader, logger: str, event: str) -> None:
    await seed_log_line(reader.session, event, logger=logger, level="error", ts=_THEN)


def _shown(entries) -> list[tuple[TimelineSource, str, str]]:
    return [(e.source, e.app, e.name) for e in entries]


@pytest.mark.asyncio
async def test_a_request_trace_is_a_log_like_any_other(reader):
    await _seed(reader, "apps.shared.observability.request", "request.finished")
    entries = await reader.search(TimelineFilter(source="logs"))
    assert _shown(entries) == [(TimelineSource.logs, "shared", "request.finished")]


@pytest.mark.asyncio
async def test_a_background_failure_is_a_log_like_any_other(reader):
    await _seed(reader, "apps.shared.queue", "queue.task_failed")
    entries = await reader.search(TimelineFilter(source="logs"))
    assert _shown(entries) == [(TimelineSource.logs, "shared", "queue.task_failed")]


@pytest.mark.asyncio
async def test_a_library_line_names_its_app_after_the_library(reader):
    """A third-party logger has no package under ``apps/``: it names itself."""
    await _seed(reader, "sqlalchemy.pool", "connection invalidated")
    entries = await reader.search(TimelineFilter(source="logs"))
    assert _shown(entries) == [(TimelineSource.logs, "sqlalchemy", "connection invalidated")]
