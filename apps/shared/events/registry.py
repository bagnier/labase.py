"""The event registry — the one collector of *what events exist* and *who listens to them*.

Two kinds of knowledge, gathered as apps are imported and mounted:

- **The catalog.** Every concrete :class:`~apps.shared.events.types.BusinessEvent` subclass
  registers itself here at class-creation time, keyed by its dotted ``kind`` and grouped by app.
  This is process-global by nature — a class is defined exactly once at import — so the catalog is
  shared by every registry instance. It powers reconstruction from a stored row
  (:meth:`event_class_for`) and the console's per-app events catalogue (:meth:`events_by_app`).
- **The subscriptions.** ``bus.on`` durable consumers and ``bus.spread`` run-everywhere handlers
  register here too. These are *per instance*, so a test can drive an isolated registry (a fresh
  :class:`EventRegistry` injected into a throwaway bus) without touching the process-wide one, while
  production shares the single :data:`registry` singleton.

The bus writes subscriptions here at mount; the listener reads them here to deliver off the trail.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.shared.events.types import BusinessEvent

# The catalog is process-global: a BusinessEvent subclass is defined once at import, so every
# EventRegistry instance shares one view of "which events exist". Only the subscriptions below are
# per-instance (test isolation). Keyed by dotted ``kind``, and grouped by the kind's app prefix.
_catalog_by_kind: dict[str, type[BusinessEvent]] = {}
_catalog_by_app: dict[str, list[type[BusinessEvent]]] = defaultdict(list)


@dataclass(frozen=True)
class Sub:
    """A durable ``bus.on`` consumer of an event type, keyed by its queue ``topic``."""

    topic: str
    as_actor: bool


class EventRegistry:
    """Collected event knowledge: the shared catalog (read via this instance) plus this instance's
    own ``on``/``spread`` subscriptions."""

    def __init__(self) -> None:
        self._async_subs: dict[type, list[Sub]] = {}
        self._spread_subs: dict[type, list[Callable[[Any], Awaitable[object]]]] = defaultdict(list)

    # ── Catalog (process-global; every instance sees the same events) ─────────────────────────

    def register_event(self, event_type: type[BusinessEvent]) -> None:
        """Record a concrete event class under its ``kind`` and its app prefix — called once per
        class from :meth:`~apps.shared.events.types.BusinessEvent.__init_subclass__`."""
        _catalog_by_kind[event_type.kind] = event_type
        app = event_type.kind.split(".", 1)[0]
        if event_type not in _catalog_by_app[app]:
            _catalog_by_app[app].append(event_type)

    def event_class_for(self, kind: str) -> type[BusinessEvent] | None:
        """The concrete ``BusinessEvent`` subclass for a dotted ``kind``, or ``None`` if unknown —
        lets the listener rebuild a typed event from a persisted ``business_events`` row."""
        return _catalog_by_kind.get(kind)

    def events_by_app(self) -> dict[str, list[type[BusinessEvent]]]:
        """The catalogue of emittable events grouped by app (app name sorted), for the console —
        each app's own vocabulary of "what can happen here"."""
        return {app: list(_catalog_by_app[app]) for app in sorted(_catalog_by_app)}

    # ── Subscriptions (per instance) ─────────────────────────────────────────────────────────

    def add_async(self, event_type: type[BusinessEvent], name: str, *, as_actor: bool) -> str:
        """Register a durable consumer ``name`` for ``event_type``; return its queue ``topic``.

        ``name`` must be unique among the event's consumers (the topic ``evt:<kind>:<name>`` keys an
        independent task row per consumer). Raises ``ValueError`` on a duplicate."""
        topic = f"evt:{event_type.kind}:{name}"
        subs = self._async_subs.setdefault(event_type, [])
        if any(s.topic == topic for s in subs):
            raise ValueError(f"duplicate consumer {name!r} for {event_type.__name__}")
        subs.append(Sub(topic=topic, as_actor=as_actor))
        return topic

    def subscribers_for(self, event_type: type) -> list[Sub]:
        """All durable subscribers keyed on the event's MRO — a base-type subscription catches
        subclasses, mirroring the bus's dispatch. Read by the listener to fan a fact out."""
        collected: list[Sub] = []
        for klass in event_type.__mro__:
            collected.extend(self._async_subs.get(klass, ()))
        return collected

    def add_spread(self, event_type: type, handler: Callable[[Any], Awaitable[object]]) -> None:
        """Register a run-everywhere ``spread`` handler for ``event_type`` (config propagation)."""
        self._spread_subs[event_type].append(handler)

    def spread_kinds(self) -> list[str]:
        """The dotted kinds that have a ``spread`` subscriber — the listener scans the trail for
        exactly these to replay per instance."""
        return [k for t in self._spread_subs if (k := getattr(t, "kind", ""))]

    def spread_handlers_for(
        self, event: BusinessEvent
    ) -> Iterator[Callable[[Any], Awaitable[object]]]:
        """The ``spread`` handlers subscribed to the event's runtime type or any base, most-specific
        first, each once — run in-process by the listener off a persisted fact."""
        seen: set[int] = set()
        for klass in type(event).__mro__:
            for handler in self._spread_subs.get(klass, ()):
                if id(handler) not in seen:
                    seen.add(id(handler))
                    yield handler


# Process-wide singleton — the catalog every event registers into, and the subscriptions the
# production bus and listener share. A fresh ``EventRegistry()`` (e.g. in a test) sees the same
# catalog but its own isolated subscriptions.
registry = EventRegistry()
