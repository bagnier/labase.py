"""Reading past the first page.

The timeline answers one page and stops. Below the hundredth row there was nothing — no cursor,
no button, no hint — so the only way further back was to guess a filter narrow enough to fit.

The cursor cannot be an id: three sources, three id spaces, no common order. It is the timestamp
of the oldest row on the page, and the next read is everything strictly older than it.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from apps.shared import clock
from apps.shared.events.models import BusinessEventRecord
from apps.timeline.infra.repository import TimelineFilter

_NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _pin_the_clock(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: _NOW)


@pytest_asyncio.fixture
async def org_with_three_facts(reader):
    """Three facts an hour apart, so "older than" has an unambiguous answer. Returns their org.

    Added through the ORM rather than ``journal_seed``: the journal's writer function leaves
    ``created_at`` to the column default on purpose — the fact's clock is the journal's, not the
    emitter's — so a seeder that goes through it cannot backdate. The e2e drivers add the model
    for the same reason.

    The org is fresh per test because the store is shared and committed: reusing one would let
    each test read its predecessors' rows, which is exactly the kind of leak a paging assertion
    cannot survive.
    """
    org = uuid.uuid7()
    for hours, verb in enumerate(("created", "edited", "deleted")):
        reader.session.add(
            BusinessEventRecord(
                app_name="todo",
                verb=verb,
                org_id=org,
                created_at=_NOW - timedelta(hours=hours),
            )
        )
    await reader.session.commit()
    return org


@pytest.mark.asyncio
async def test_without_a_cursor_the_page_starts_at_the_newest(reader, org_with_three_facts):
    flt = TimelineFilter(org_id=str(org_with_three_facts))

    entries = await reader.search(flt)

    assert [e.name for e in entries] == ["todo.created", "todo.edited", "todo.deleted"]


@pytest.mark.asyncio
async def test_a_cursor_returns_only_what_is_strictly_older(reader, org_with_three_facts):
    """Strictly: the row the cursor was read off is the last one already shown, so including it
    would repeat it at the top of every page."""
    flt = TimelineFilter(org_id=str(org_with_three_facts), before_ts=_NOW - timedelta(hours=1))

    entries = await reader.search(flt)

    assert [e.name for e in entries] == ["todo.deleted"]


@pytest.mark.asyncio
async def test_a_cursor_past_the_oldest_row_returns_nothing(reader, org_with_three_facts):
    """What the end of the timeline looks like — no next page to offer."""
    flt = TimelineFilter(org_id=str(org_with_three_facts), before_ts=_NOW - timedelta(days=1))

    entries = await reader.search(flt)

    assert [e.name for e in entries] == []
