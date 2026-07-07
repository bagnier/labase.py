"""Dashboard compositions — org's *pull* collaboration surface, carried by the event bus.

Org-scoped apps contribute one :class:`Overview` each to the org dashboard by answering the
:class:`OverviewQuery` query event (``host.events.on(OverviewQuery, provider)`` at mount). The
org dashboard gathers them at runtime with ``bus.collect(OverviewQuery(...))`` — a failing
provider is isolated, not fatal. Providers stay ignorant of one another and of the dashboard.

Each overview carries both a *web view* (the app's own Jinja partial, rendered on the
dashboard) and *structured data* (a JSON-serializable dict, exposed via the REST endpoint).
By convention ``data`` holds ``lines`` (short metric strings) and ``recent`` (recent item
labels); both surfaces render the same content.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class Overview:
    key: str  # context id, e.g. "todo"
    title: str  # human title, e.g. "To-do"
    icon: str  # phosphor icon name
    href: str  # link into the app (relative to the org handle)
    template: str  # the app's own Jinja partial (web view)
    data: dict = field(default_factory=dict)  # JSON-serializable; "lines"/"recent"


@dataclass(frozen=True)
class OverviewQuery:
    """Asked by the org dashboard; each app answers with its :class:`Overview`."""

    session: AsyncSession
    org_id: uuid.UUID
