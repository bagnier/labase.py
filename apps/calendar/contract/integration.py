"""How the calendar context plugs into the running app.

Single composition entry (:func:`mount`, called from :mod:`apps.main`): mounts the org-scoped
router, answers the dashboard ``OverviewQuery`` (upcoming events) and the server-wide
``ConsoleOverviewQuery`` (total events), and seeds a welcome event on ``OrgCreated``.
"""

import uuid
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from apps.calendar.contract import settings
from apps.calendar.infra.repository import CalendarEventRepository, count_all
from apps.calendar.infra.router import router
from apps.organizations.contract import ORG_PREFIX
from apps.organizations.contract.events import OrgCreated
from apps.organizations.contract.overviews import Overview, OverviewQuery
from apps.organizations.contract.queries import seed_with_owner
from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.contract.settings import (
    SettingsChanged,
    SupabaseLink,
    declare_app_settings,
    feature_switch,
    get_app_settings,
)
from apps.shared import clock
from apps.shared.host import Host, NavItem
from apps.shared.text import overview_from_count

_RECENT = 3
_WELCOME_TITLE = "Welcome to your team calendar"


def mount(host: Host) -> None:
    # Console presence is kept even when disabled, so an admin can see and re-enable the app.
    host.events.on(ConsoleOverviewQuery, _console_overview)
    _declare_settings()
    host.reserve("calendar")  # reserved even when disabled, to keep the slug from being squatted
    if not get_app_settings("calendar").enabled:
        return
    settings.read()
    host.events.on(SettingsChanged, settings.reload)
    host.app.include_router(router, prefix=ORG_PREFIX)
    host.register_nav(NavItem("Calendar", "calendar-dots", "calendar", "/calendar", order=20))
    host.events.on(OverviewQuery, _overview)
    host.events.on(OrgCreated, _seed)


def _declare_settings() -> None:
    settings.group = declare_app_settings(
        "calendar",
        defs=[feature_switch()],
        supabase=SupabaseLink("Browse events in Supabase", table="calendar_events"),
    )


async def _overview(query: OverviewQuery) -> Overview:
    upcoming = await CalendarEventRepository(query.session, query.org_id).upcoming()
    n = len(upcoming)
    lines = [f"{n} upcoming"] if upcoming else ["No upcoming events"]
    return Overview(
        key="calendar",
        title="Calendar",
        icon="calendar-dots",
        href="calendar",
        template="calendar/_overview.html",
        data={"lines": lines, "recent": [e.title for e in upcoming[:_RECENT]]},
    )


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    total = await count_all(query.session)
    lines = overview_from_count(total, "event", "No events yet")
    return ConsoleOverview(
        key="calendar", title="Calendar", icon="calendar-dots", data={"lines": lines}
    )


async def _seed(event: OrgCreated) -> None:
    """Drop a single welcome event dated today, so a brand-new org's calendar isn't empty.

    Production-only: ``OrgCreated`` is suppressed in the test schema, so this never runs under
    the E2E drivers (mirrors the todo/files/learning seed handlers)."""

    async def seed(session: AsyncSession, owner_id: uuid.UUID) -> None:
        start = clock.now().replace(hour=9, minute=0, second=0, microsecond=0)
        await CalendarEventRepository(session, event.org_id).add(
            owner_id,
            _WELCOME_TITLE,
            start,
            start + timedelta(hours=1),
            description="Edit or delete this sample event to get started.",
        )

    await seed_with_owner(event.org_id, seed)
