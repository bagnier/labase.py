"""Which app a timeline entry belongs to — the axis the console browses by, across three sources.

A business fact states its app on its own column. The other two have to name themselves at the
boundary that builds them, and both read it off the *logger*: ``apps.auth.infra.router`` is auth's,
``sqlalchemy.pool`` is the library's. An occurrence carries that logger in its captured context,
which is what makes the pivot from an issue back to the code that raised it work at all.

The pill that offers the axis has to agree with the filter that applies it: a value the filter
accepts and the dropdown never lists is a filter an admin cannot reach.
"""

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
    """The store is shared and committed — the day files this replaced gave each test a scratch
    directory. These tests assert over *every* ``logs`` entry, so they start from empty."""
    await clear_log_lines(reader.session)
    yield
    await clear_log_lines(reader.session)


def _occurrence(title: str, logger: str) -> IssueOccurrence:
    return IssueOccurrence(
        ts=_NOW, title=title, context={"logger": logger, "stack": "…"}, issue_id=uuid.uuid7()
    )


def test_an_occurrence_names_the_app_that_raised_not_its_own_title():
    """An issue's title is ``ValueError: user 42 not found`` — an exception type and a message,
    never a dotted app prefix. Splitting it on the first dot yielded the whole title as the app,
    so no ``app`` filter could ever return an occurrence."""
    entry = _from_issue(_occurrence("ValueError: user 42 not found", "apps.todo.infra.router"))

    assert entry.app == "todo"


def test_an_occurrence_from_a_library_names_the_library():
    """Same rule the firehose already follows, so both sources of a failure agree."""
    entry = _from_issue(_occurrence("TimeoutError: pool exhausted", "sqlalchemy.pool"))

    assert entry.app == "sqlalchemy"


def test_an_occurrence_with_no_logger_claims_no_app():
    """A hand-inserted or legacy row has no logger to read; it must not invent one."""
    entry = _from_issue(
        IssueOccurrence(ts=_NOW, title="ValueError: boom", context={}, issue_id=uuid.uuid7())
    )

    assert entry.app == ""


@pytest.mark.asyncio
async def test_the_app_pill_offers_every_app_the_filter_accepts(reader):
    """The filter runs over all three sources; a facet counting only business rows left ``shared``
    and every library filterable but unlisted — reachable by hand-editing the URL and no other way.
    """
    await seed_log_line(reader.session, "q.failed", logger="apps.shared.queue", ts=_THEN)
    await seed_log_line(reader.session, "pool gone", logger="sqlalchemy.pool", ts=_THEN)

    # A facet clears the categorical filters on purpose (every pill offers all its values), so
    # the date window is what keeps the shared journal's rows out of this assertion.
    facets = await reader.facets(
        TimelineFilter(
            from_dt=datetime(2026, 7, 12, 9, tzinfo=UTC),
            to_dt=datetime(2026, 7, 12, 11, tzinfo=UTC),
        )
    )

    assert [option["value"] for option in facets["app"]] == ["shared", "sqlalchemy"]
