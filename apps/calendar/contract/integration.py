"""How the calendar context plugs into the running app.

Single composition entry (:func:`mount`, called from :mod:`apps.main`): mounts the org-scoped
router, answers the dashboard ``OverviewQuery`` (upcoming events) and the server-wide
``ConsoleOverviewQuery`` (total events), and seeds a welcome event on ``OrganizationCreated``.
"""

import uuid
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from apps.calendar.domain.models import CalendarEvent
from apps.calendar.infra.repository import CalendarEventRepository
from apps.calendar.infra.router import router
from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.organizations.contract import ORG_PREFIX
from apps.organizations.contract.events import OrganizationCreated
from apps.organizations.contract.overviews import Overview, OverviewQuery
from apps.organizations.contract.queries import spawn_org_seed
from apps.shared import clock
from apps.shared.host import AppManifest, Host, MountPhase, NavItem
from apps.shared.persistence.repository import count_all
from apps.shared.settings import SettingsDeclaration, SupabaseLink, feature_switch
from apps.shared.text import overview_from_count

PHASE = MountPhase.ORG

_RECENT = 3
_WELCOME_TITLE = "Welcome to your team calendar"


def mount(host: Host) -> None:
    host.register_app(
        AppManifest(
            settings=_declare_settings(),
            on=[(ConsoleOverviewQuery, _console_overview)],
            routers=[(router, ORG_PREFIX)],
            nav=[NavItem("Calendar", "calendar-dots", "calendar", "/calendar", order=30)],
            when_enabled=[(OverviewQuery, _overview), (OrganizationCreated, _seed)],
        )
    )


def _declare_settings() -> SettingsDeclaration:
    return SettingsDeclaration(
        app_name="calendar",
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
    total = await count_all(query.session, CalendarEvent)
    lines = overview_from_count(total, "event", "No events yet")
    return ConsoleOverview(
        key="calendar", title="Calendar", icon="calendar-dots", data={"lines": lines}
    )


async def _seed(event: OrganizationCreated) -> None:
    """Drop a single welcome event dated today, so a brand-new org's calendar isn't empty.

    Suppressed in the test schema (via ``spawn_org_seed``), so this never runs under the E2E
    drivers (mirrors the todo/files/learning seed handlers)."""
    spawn_org_seed(event.org_id, _seed_welcome)


async def _seed_welcome(session: AsyncSession, org_id: uuid.UUID, owner_id: uuid.UUID) -> None:
    start = clock.now().replace(hour=9, minute=0, second=0, microsecond=0)
    await CalendarEventRepository(session, org_id).add(
        owner_id,
        _WELCOME_TITLE,
        start,
        start + timedelta(hours=1),
        description="Edit or delete this sample event to get started.",
    )
