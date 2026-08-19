"""Which app a timeline entry belongs to — the axis the console browses by, across three sources.

A business fact states its app on its own column. The other two have to name themselves at the
boundary that builds them, and both read it off the *logger*: ``apps.auth.infra.router`` is auth's,
``sqlalchemy.pool`` is the library's. An occurrence carries that logger in its captured context,
which is what makes the pivot from an issue back to the code that raised it work at all.

The pill that offers the axis has to agree with the filter that applies it: a value the filter
accepts and the dropdown never lists is a filter an admin cannot reach.
"""

from datetime import UTC, datetime

import pytest

from apps.issues.contract.queries import IssueOccurrence
from apps.shared import clock
from apps.shared.config import get_technical_settings
from apps.shared.observability import firehose
from apps.shared.observability.firehose import append_firehose
from apps.timeline.infra.repository import TimelineFilter, _from_issue

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


def _occurrence(title: str, logger: str) -> IssueOccurrence:
    return IssueOccurrence(ts=_NOW, title=title, context={"logger": logger, "stack": "…"})


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
    entry = _from_issue(IssueOccurrence(ts=_NOW, title="ValueError: boom", context={}))

    assert entry.app == ""


@pytest.mark.asyncio
async def test_the_app_pill_offers_every_app_the_filter_accepts(reader):
    """The filter runs over all three sources; a facet counting only business rows left ``shared``
    and every library filterable but unlisted — reachable by hand-editing the URL and no other way.
    """
    append_firehose(
        {"timestamp": _THEN, "level": "error", "logger": "apps.shared.queue", "event": "q.failed"}
    )
    append_firehose(
        {"timestamp": _THEN, "level": "error", "logger": "sqlalchemy.pool", "event": "pool gone"}
    )

    # A facet clears the categorical filters on purpose (every pill offers all its values), so
    # the date window is what keeps the shared journal's rows out of this assertion.
    facets = await reader.facets(
        TimelineFilter(
            from_dt=datetime(2026, 7, 12, 9, tzinfo=UTC),
            to_dt=datetime(2026, 7, 12, 11, tzinfo=UTC),
        )
    )

    assert [option["value"] for option in facets["app"]] == ["shared", "sqlalchemy"]
