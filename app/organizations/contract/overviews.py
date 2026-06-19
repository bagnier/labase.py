"""The dashboard-overview contract — the organizations context's public surface.

Org-scoped apps contribute one :class:`Overview` each to the org dashboard. The only
place that wires providers in is the composition root (:mod:`app.overviews`), which
auto-discovers every ``app/<ctx>/contract/overview.py`` exposing a module-level
``overview`` coroutine — no central list. Providers stay ignorant of one another and of
the dashboard; they only know their own repository.

Each overview carries both a *web view* (the app's own Jinja partial, rendered on the
dashboard) and *structured data* (a JSON-serializable dict, exposed via the REST endpoint).
By convention ``data`` holds ``lines`` (short metric strings) and ``recent`` (recent item
labels); both surfaces render the same content.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Overview:
    key: str  # context id, e.g. "todo"
    title: str  # human title, e.g. "To-do"
    icon: str  # phosphor icon name
    href: str  # link into the app (relative to the org handle)
    template: str  # the app's own Jinja partial (web view)
    data: dict = field(default_factory=dict)  # JSON-serializable; "lines"/"recent"


# (session, org_id) -> Overview — org-scoped, no user context.
OverviewProvider = Callable[[AsyncSession, uuid.UUID], Awaitable[Overview]]

_providers: dict[str, OverviewProvider] = {}


def register_overview(ctx: str, provider: OverviewProvider) -> None:
    _providers[ctx] = provider


async def collect_overviews(session: AsyncSession, org_id: uuid.UUID) -> list[Overview]:
    """Run every registered provider in deterministic (ctx-sorted) order.

    A failing provider must not break the dashboard: it is logged and skipped.
    """
    overviews: list[Overview] = []
    for ctx in sorted(_providers):
        try:
            overviews.append(await _providers[ctx](session, org_id))
        except Exception:
            _log.exception("overview provider %r failed; skipping", ctx)
    return overviews
