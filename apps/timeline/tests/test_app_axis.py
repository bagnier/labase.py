"""The ``app`` axis across the three sources, and the pill offering every value the filter
accepts."""

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from apps.issues.contract.queries import IssueOccurrence
from apps.shared import clock
from apps.shared.logs import sink
from apps.shared.settings.env import get_technical_settings
from apps.shared.tests.log_seed import clear_log_lines, seed_log_line
from apps.timeline.infra.repository import TimelineFilter, _from_issue

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
    """These tests assert over every ``logs`` entry of the shared store: start empty."""
    await clear_log_lines(reader.session)
    yield
    await clear_log_lines(reader.session)


def _occurrence(title: str, logger: str) -> IssueOccurrence:
    return IssueOccurrence(
        ts=_NOW, title=title, context={"logger": logger, "stack": "…"}, issue_id=uuid.uuid7()
    )


def test_an_occurrence_names_the_app_that_raised_not_its_own_title():
    """Not from the title, ``ValueError: user 42 not found``."""
    entry = _from_issue(_occurrence("ValueError: user 42 not found", "apps.todo.infra.router"))

    assert entry.app == "todo"


def test_an_occurrence_from_a_library_names_the_library():
    entry = _from_issue(_occurrence("TimeoutError: pool exhausted", "sqlalchemy.pool"))

    assert entry.app == "sqlalchemy"


def test_an_occurrence_with_no_logger_claims_no_app():
    entry = _from_issue(
        IssueOccurrence(ts=_NOW, title="ValueError: boom", context={}, issue_id=uuid.uuid7())
    )

    assert entry.app == ""


@pytest.mark.asyncio
async def test_the_app_pill_offers_every_app_the_filter_accepts(reader):
    await seed_log_line(reader.session, "q.failed", logger="apps.shared.queue", ts=_THEN)
    await seed_log_line(reader.session, "pool gone", logger="sqlalchemy.pool", ts=_THEN)

    # Facets ignore categorical filters: the date window keeps other rows out.
    facets = await reader.facets(
        TimelineFilter(
            from_dt=datetime(2026, 7, 12, 9, tzinfo=UTC),
            to_dt=datetime(2026, 7, 12, 11, tzinfo=UTC),
        )
    )

    assert [option["value"] for option in facets["app"]] == ["shared", "sqlalchemy"]
