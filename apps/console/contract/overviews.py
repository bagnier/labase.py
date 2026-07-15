"""Server-wide overviews — the console's *pull* surface, carried by the event bus.

Mirrors :mod:`apps.organizations.contract.overviews` but **server-wide**: there is no ``org_id``,
the session is the BYPASSRLS admin session, and each app aggregates across *every* organisation.
Apps answer :class:`ConsoleOverviewQuery` via ``host.events.on(ConsoleOverviewQuery, provider)``
at mount; the console gathers them at runtime with ``bus.collect`` (a failing provider is
isolated, not fatal).
"""

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

#: Console landing sections, in display order. ``operations`` groups the monitoring
#: screens (issues, metrics, logs) so they are visible at a glance; ``identity`` groups
#: the who-and-tenancy screens (users, organisations, profiles) in one place; ``features``
#: are the product apps; ``configuration`` are the platform/foundation settings.
SECTIONS: tuple[str, ...] = ("operations", "identity", "features", "configuration")


@dataclass(frozen=True)
class ConsoleOverview:
    key: str  # context id, e.g. "files"
    title: str  # human title
    icon: str  # phosphor icon name
    data: dict = field(default_factory=dict)  # JSON-serializable; "lines"
    group: str | None = None  # fold into one console tile with others sharing this group
    section: str = "features"  # console landing section — one of SECTIONS
    href: str | None = None  # card link; defaults to /console/{key} when None


@dataclass(frozen=True)
class ConsoleOverviewQuery:
    """Asked by the console; each app answers with a server-wide :class:`ConsoleOverview`."""

    session: AsyncSession  # BYPASSRLS admin session — spans all organisations
