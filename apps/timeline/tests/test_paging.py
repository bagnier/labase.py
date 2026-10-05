"""Paging: the cursor is the oldest row's timestamp, the only order the sources share."""

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
    """Three facts an hour apart in a fresh org, returned. Through the ORM: the writer function
    cannot backdate."""
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
    """Strictly: the cursor's row is already shown."""
    flt = TimelineFilter(org_id=str(org_with_three_facts), before_ts=_NOW - timedelta(hours=1))

    entries = await reader.search(flt)

    assert [e.name for e in entries] == ["todo.deleted"]


@pytest.mark.asyncio
async def test_a_cursor_past_the_oldest_row_returns_nothing(reader, org_with_three_facts):
    flt = TimelineFilter(org_id=str(org_with_three_facts), before_ts=_NOW - timedelta(days=1))

    entries = await reader.search(flt)

    assert [e.name for e in entries] == []
