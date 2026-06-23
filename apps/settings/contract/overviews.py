"""Server-wide overviews — the console's *pull* surface, carried by the event bus.

Mirrors :mod:`apps.organizations.contract.overviews` but **server-wide**: there is no ``org_id``,
the session is the BYPASSRLS admin session, and each app aggregates across *every* organisation.
Apps answer :class:`ConsoleOverviewQuery` via ``host.events.on(ConsoleOverviewQuery, provider)``;
the console gathers them with ``host.events.collect`` (a failing provider is isolated, not fatal).
"""

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ConsoleOverview:
    key: str  # context id, e.g. "files"
    title: str  # human title
    icon: str  # phosphor icon name
    data: dict = field(default_factory=dict)  # JSON-serializable; "lines"


@dataclass(frozen=True)
class ConsoleOverviewQuery:
    """Asked by the console; each app answers with a server-wide :class:`ConsoleOverview`."""

    session: AsyncSession  # BYPASSRLS admin session — spans all organisations
