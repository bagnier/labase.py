"""The event registry — the one collector of *what events exist* and *who listens to them*.

Three kinds of knowledge, gathered as apps are imported and mounted:

- **The catalog.** Every concrete :class:`~apps.shared.events.types.BusinessEvent` subclass
  registers itself here at class-creation time, keyed by its dotted ``kind``. This is process-global
  by nature — a class is defined exactly once at import — so the catalog is shared by every registry
  instance. It powers reconstruction from a stored row (:meth:`event_class_for`).
- **The ownership.** At mount, an app *declares* the events it emits (:meth:`declare`), recording
  the **owner app** per event. ``emit`` refuses an undeclared event (a mounted app only emits what
  it declared), and the console reads ownership as the per-app catalogue (:meth:`events_by_app`).
  The declared namespace must match the kind prefix (``settings.*`` → the ``settings`` owner), so an
  app cannot claim another's events.
- **The subscriptions.** ``bus.on`` durable consumers (each tagged with the **listening app**) and
  ``bus.spread`` run-everywhere handlers register here too.

Ownership and subscriptions are *per instance*, so a test can drive an isolated registry (a fresh
:class:`EventRegistry` injected into a throwaway bus) without touching the process-wide one, while
production shares the single :data:`registry` singleton. The catalog stays shared (import-time).

The bus writes ownership/subscriptions here at mount; the listener reads subscriptions here to
deliver off the trail.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.shared.events.types import BusinessEvent

# The catalog is process-global: a BusinessEvent subclass is defined once at import, so every
# EventRegistry instance shares one view of "which kinds exist" (for reconstruction). Ownership and
# subscriptions below are per-instance (a test isolates them; production shares the singleton).
_catalog_by_kind: dict[str, type[BusinessEvent]] = {}


@dataclass(frozen=True)
class Sub:
    """A durable ``bus.on`` consumer of an event type: the queue ``topic`` it feeds and the app that
    listens (for the console's event → reaction graph)."""

    topic: str
    as_actor: bool
    app: str


class EventRegistry:
    """Collected event knowledge: the shared catalog (read via this instance), plus this instance's
    ownership (declared events → owner app) and ``on``/``spread`` subscriptions."""

    def __init__(self) -> None:
        self._owner_by_type: dict[type[BusinessEvent], str] = {}
        self._async_subs: dict[type, list[Sub]] = {}
        self._spread_subs: dict[type, list[Callable[[Any], Awaitable[object]]]] = defaultdict(list)

    # ── Catalog (process-global; every instance sees the same kinds) ──────────────────────────

    def register_event(self, event_type: type[BusinessEvent]) -> None:
        """Record a concrete event class under its ``kind`` — called once per class from
        :meth:`~apps.shared.events.types.BusinessEvent.__init_subclass__`, for reconstruction."""
        _catalog_by_kind[event_type.kind] = event_type

    def event_class_for(self, kind: str) -> type[BusinessEvent] | None:
        """The concrete ``BusinessEvent`` subclass for a dotted ``kind``, or ``None`` if unknown —
        lets the listener rebuild a typed event from a persisted ``business_events`` row."""
        return _catalog_by_kind.get(kind)

    # ── Ownership (declared at mount, per instance) ──────────────────────────────────────────

    def declare(self, app: str, *event_types: type[BusinessEvent]) -> None:
        """Record that ``app`` owns (emits) each of ``event_types``. The event's kind prefix must be
        ``app`` (``todo.*`` → ``todo``), so an app cannot claim another's events; re-declaring the
        same event for the same app is idempotent, for a different app is an error."""
        for event_type in event_types:
            prefix = event_type.kind.split(".", 1)[0]
            if prefix != app:
                raise ValueError(
                    f"{app!r} cannot declare {event_type.__name__}: "
                    f"kind {event_type.kind!r} is owned by {prefix!r}"
                )
            owner = self._owner_by_type.get(event_type)
            if owner is not None and owner != app:
                raise ValueError(f"{event_type.__name__} already declared by {owner!r}")
            self._owner_by_type[event_type] = app

    def is_declared(self, event_type: type[BusinessEvent]) -> bool:
        """Whether some app declared it — the gate ``emit`` checks before persisting a fact."""
        return event_type in self._owner_by_type

    def owner_of(self, event_type: type[BusinessEvent]) -> str | None:
        """The app that declared (emits) this event, or ``None`` if undeclared."""
        return self._owner_by_type.get(event_type)

    def events_by_app(self) -> dict[str, list[type[BusinessEvent]]]:
        """The declared events grouped by owner app (app name sorted), for the console — each app's
        own vocabulary of "what it emits"."""
        by_app: dict[str, list[type[BusinessEvent]]] = defaultdict(list)
        for event_type, app in self._owner_by_type.items():
            by_app[app].append(event_type)
        return {app: by_app[app] for app in sorted(by_app)}

    # ── Subscriptions (per instance) ─────────────────────────────────────────────────────────

    def add_async(
        self, event_type: type[BusinessEvent], name: str, *, as_actor: bool, app: str
    ) -> str:
        """Register a durable consumer ``name`` (in ``app``) for ``event_type``; return its topic.

        ``name`` must be unique among the event's consumers (the topic ``evt:<kind>:<name>`` keys an
        independent task row per consumer). Raises ``ValueError`` on a duplicate."""
        topic = f"evt:{event_type.kind}:{name}"
        subs = self._async_subs.setdefault(event_type, [])
        if any(s.topic == topic for s in subs):
            raise ValueError(f"duplicate consumer {name!r} for {event_type.__name__}")
        subs.append(Sub(topic=topic, as_actor=as_actor, app=app))
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
