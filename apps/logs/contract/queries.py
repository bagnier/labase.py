"""Aggregate read queries other contexts may ask of the logs timeline.

The underlying sources (business-events trail, error events) are admin-only tables — RLS grants
no member read — so these run on the admin session, hard-scope the ``org_id`` filter
in code, and return **aggregates only** (day/source counts, never rows): what an org
member may see about their own org's pulse without opening the admin timeline.
"""

import uuid
from datetime import timedelta

from apps.logs.infra.repository import LogFilter, LogReader
from apps.shared import clock
from apps.shared.persistence.database import admin_session_factory


async def org_activity(org_id: uuid.UUID, *, days: int = 14) -> dict[str, dict[str, int]]:
    """Per-day, per-source event counts for one org over a trailing window
    (the :meth:`LogReader.activity` shape: ``{iso_day: {source: count}}``)."""
    since = clock.now() - timedelta(days=days - 1)
    flt = LogFilter(org_id=str(org_id), from_dt=since)
    async with admin_session_factory()() as session:
        return await LogReader(session).activity(flt)
