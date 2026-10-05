"""What this process's mounts activated: which events it emits, and who reacts.

Written by the bus at mount; read directly by the listener (to deliver) and the console (its
event → reaction graph). Unlike the catalog, a test can build its own: ``EventBus(EventWiring())``.
A test that needs the real fan-out registers on the live :data:`wiring` and puts it back with
:meth:`~EventWiring.snapshot` / :meth:`~EventWiring.restore`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.shared.events.types import BusinessEvent

SpreadHandler = Callable[[Any], Awaitable[object]]


@dataclass(frozen=True)
class Reaction:
    """A durable ``bus.on`` consumer: its ``name``, the queue ``topic`` it feeds, and the listening
    ``app``."""

    name: str
    topic: str
    as_actor: bool
    app: str


@dataclass(frozen=True)
class WiringSnapshot:
    """A copy of a wiring, deep enough to survive later registrations."""

    owners: dict[type[BusinessEvent], str]
    reactions: dict[type[BusinessEvent], list[Reaction]]
    spread: dict[type[BusinessEvent], list[SpreadHandler]]


class EventWiring:
    """Who emits what, and who reacts to it."""

    def __init__(self) -> None:
        self._owner_by_type: dict[type[BusinessEvent], str] = {}
        self._reactions: dict[type[BusinessEvent], list[Reaction]] = {}
        self._spread: dict[type[BusinessEvent], list[SpreadHandler]] = defaultdict(list)

    # ── Ownership: who emits what ────────────────────────────────────────────────────────────

    def declare(self, *event_types: type[BusinessEvent]) -> None:
        """Activate events, each owned by the app its ``app_name`` names: an app cannot claim
        another's events. Idempotent.

        Raises ``ValueError`` on a class with no ``kind`` (usually an abstract base passed instead
        of its concrete subclasses): the listener could not rebuild it from a record."""
        for event_type in event_types:
            if not event_type.kind:
                raise ValueError(
                    f"{event_type.__name__} declares no app_name/verb, so it has no kind — "
                    "an unnamed fact cannot be persisted or rebuilt"
                )
            self._owner_by_type[event_type] = event_type.app_name

    def is_declared(self, event_type: type[BusinessEvent]) -> bool:
        return event_type in self._owner_by_type

    def owner_of(self, event_type: type[BusinessEvent]) -> str | None:
        """The app that declared this event, or ``None``."""
        return self._owner_by_type.get(event_type)

    def by_app(self) -> dict[str, list[type[BusinessEvent]]]:
        """Declared events grouped by owner app, apps sorted."""
        grouped: dict[str, list[type[BusinessEvent]]] = defaultdict(list)
        for event_type, app in self._owner_by_type.items():
            grouped[app].append(event_type)
        return {app: grouped[app] for app in sorted(grouped)}

    # ── Reactions: who listens ───────────────────────────────────────────────────────────────

    def add_consumer(
        self, event_type: type[BusinessEvent], name: str, *, as_actor: bool, app: str
    ) -> str:
        """Register a durable consumer and return its queue topic, ``evt:<kind>:<name>``.

        Raises ``ValueError`` on a kindless class (as :meth:`declare`) and on a topic already
        taken by any event: the queue keys its handlers by topic, so two consumers sharing one
        would silently overwrite each other."""
        if not event_type.kind:
            raise ValueError(
                f"{event_type.__name__} names no kind, so it has no topic to register a consumer "
                "under — an unnamed fact cannot be persisted or rebuilt"
            )
        topic = f"evt:{event_type.kind}:{name}"
        if any(r.topic == topic for rs in self._reactions.values() for r in rs):
            raise ValueError(f"duplicate topic {topic!r}: another consumer already claims it")
        self._reactions.setdefault(event_type, []).append(
            Reaction(name=name, topic=topic, as_actor=as_actor, app=app)
        )
        return topic

    def consumers_of(self, event_type: type) -> list[Reaction]:
        """Consumers of the type or any of its bases: subscribing a base catches its subclasses."""
        collected: list[Reaction] = []
        for klass in event_type.__mro__:
            collected.extend(self._reactions.get(klass, ()))
        return collected

    def reactions(self) -> dict[type[BusinessEvent], list[Reaction]]:
        """A copy of every event type that has a durable consumer, with its consumers."""
        return {event_type: list(rs) for event_type, rs in self._reactions.items()}

    # ── Spread handlers: run everywhere ──────────────────────────────────────────────────────

    def add_spread_handler(self, event_type: type[BusinessEvent], handler: SpreadHandler) -> None:
        self._spread[event_type].append(handler)

    def spread_kinds(self) -> list[str]:
        """The kinds the listener scans the journal for. A handler on an abstract base has no kind
        here; its subclasses reach it through :meth:`spread_handlers_for`."""
        return [k for t in self._spread if (k := t.kind)]

    def spread_handlers_for(self, event: BusinessEvent) -> Iterator[SpreadHandler]:
        """Handlers for the event's type or any base, most specific first, each once."""
        seen: set[int] = set()
        for klass in type(event).__mro__:
            for handler in self._spread.get(klass, ()):
                if id(handler) not in seen:
                    seen.add(id(handler))
                    yield handler

    # ── Isolation, for a test that must register on the live bus ─────────────────────────────

    def snapshot(self) -> WiringSnapshot:
        return WiringSnapshot(
            owners=dict(self._owner_by_type),
            reactions={t: list(rs) for t, rs in self._reactions.items()},
            spread={t: list(hs) for t, hs in self._spread.items()},
        )

    def restore(self, snapshot: WiringSnapshot) -> None:
        """Put back a :meth:`snapshot`, dropping whatever was registered since."""
        self._owner_by_type = dict(snapshot.owners)
        self._reactions = {t: list(rs) for t, rs in snapshot.reactions.items()}
        self._spread = defaultdict(list, {t: list(hs) for t, hs in snapshot.spread.items()})


# Readers import this directly rather than through the bus: reading who reacts needs no emitter.
wiring = EventWiring()
