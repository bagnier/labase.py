"""The app-wide integration machinery — the generic event bus every context wires into.

One mechanism, two primitives on :class:`EventBus` (type-keyed, no magic string names):

- ``emit(event)`` — *push/command*: run every handler, propagate the first exception (so a
  caller can compensate), return their results. Used for ``UserCreated`` (org creation),
  ``OrgCreated`` (welcome seeding).
- ``collect(query)`` — *pull/query*: run every handler, isolate failures (log + skip),
  return the successful results. Used for the org dashboard (``OverviewQuery``); future
  console/public surfaces are just more query events — nothing concrete on :class:`Host`.

:class:`Host` only carries the bus and the reserved-slug claim. Contexts own their own event
dataclasses and never import one another; they plug in via ``contract/integration.py``'s
``register(app, host)``, wired from the composition root :mod:`app.main`. ``host`` is the
production singleton; tests can build a fresh :class:`Host` in isolation.
"""

import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from app.shared.names import reserve as _reserve_slugs

_log = logging.getLogger(__name__)

E = TypeVar("E")


class EventBus:
    """Type-keyed async pub/sub. Handlers are dispatched by the event's runtime type."""

    def __init__(self) -> None:
        self._subs: dict[type, list[Callable[..., Awaitable[Any]]]] = defaultdict(list)

    def on(self, event_type: type[E], handler: Callable[[E], Awaitable[Any]]) -> None:
        self._subs[event_type].append(handler)

    async def emit(self, event: object) -> list[Any]:
        """Run every handler for this event's type, in order; propagate, return their returns.

        A handler may return a value the emitter needs — e.g. the org context returns the new
        ``org_id`` when reacting to ``UserCreated``. Exceptions propagate (so the caller can
        compensate).
        """
        return [await handler(event) for handler in self._subs[type(event)]]

    async def collect(self, query: object) -> list[Any]:
        """Run every handler for this query's type and gather successful returns.

        A failing handler must not break the aggregate (e.g. one app's overview must not take
        down the dashboard): it is logged and skipped.
        """
        results: list[Any] = []
        for handler in self._subs[type(query)]:
            try:
                results.append(await handler(query))
            except Exception:
                _log.exception("query handler %r failed; skipping", handler)
        return results


@dataclass
class Host:
    events: EventBus = field(default_factory=EventBus)

    def reserve(self, *slugs: str) -> None:
        """Claim URL slugs so no org handle can take them (see :mod:`app.shared.names`)."""
        _reserve_slugs(*slugs)


host = Host()
