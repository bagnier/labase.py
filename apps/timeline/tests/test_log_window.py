"""The ``logs`` source's default window bounds an unfiltered screen; naming a subject drops it
(see ``TimelineFilter.is_narrowed``)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from apps.shared import clock
from apps.shared.tests.log_seed import clear_log_lines, seed_log_line
from apps.timeline.infra.repository import TimelineFilter

_NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
_LAST_WEEK = _NOW - timedelta(days=6)  # past the default window


@pytest.fixture(autouse=True)
def _pin_the_clock(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: _NOW)


@pytest_asyncio.fixture(autouse=True)
async def _only_my_lines(reader):
    await clear_log_lines(reader.session)
    yield
    await clear_log_lines(reader.session)


@pytest.mark.asyncio
async def test_an_unfiltered_timeline_keeps_its_window(reader):
    await seed_log_line(reader.session, "request.finished", ts=_LAST_WEEK)

    entries = await reader.search(TimelineFilter(source="logs"))

    assert [e.name for e in entries] == []


@pytest.mark.asyncio
async def test_correlating_a_request_reaches_past_that_window(reader):
    request_id = str(uuid.uuid7())
    await seed_log_line(reader.session, "request.finished", ts=_LAST_WEEK, request_id=request_id)

    entries = await reader.search(TimelineFilter(source="logs", request_id=request_id))

    assert [e.name for e in entries] == ["request.finished"]


@pytest.mark.asyncio
async def test_searching_for_text_reaches_past_it_too(reader):
    await seed_log_line(reader.session, "auth.login_failed", ts=_LAST_WEEK)

    entries = await reader.search(TimelineFilter(source="logs", text="login_failed"))

    assert [e.name for e in entries] == ["auth.login_failed"]


def test_a_live_timeline_refetches_itself_and_a_pinned_one_does_not(driver):
    """Same macro and rule as the Tasks history: only an end bound pauses it."""
    driver.sign_in_as_admin("timeline-live@example.com")

    def page(**params) -> str:
        return (
            driver.client()
            .get("/console/timeline", params=params, headers={"accept": "text/html"})
            .text
        )

    assert [
        "every 30s" in page(),
        "every 30s" in page(from_dt="2026-09-02T03:00"),
        "every 30s" in page(to_dt="2026-09-02T09:00"),
        "every 30s" in page(sort="level"),
    ] == [True, True, False, False]
