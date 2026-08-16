"""The event wiring — what *this process* activated at mount.

One question: given the events that exist (:mod:`apps.shared.events.catalog`), which of them does
this process emit, and who reacts to them. Two halves, written by the same caller at the same
moment — an app's ``mount`` going through the bus:

- **ownership** — an app *declares* the events it emits (:meth:`declare`), recording the owner app
  read off the event's own ``app_name``. ``emit`` refuses an undeclared event (a disabled app never
  declares, so its facts cannot be emitted), and the console reads ownership as the per-app
  catalogue.
- **reactions** — ``bus.on`` durable consumers (each tagged with the listening app) and
  ``bus.spread`` run-everywhere handlers.

Per instance, unlike the catalog — but the *process* has one, the :data:`wiring` singleton below,
and it is imported rather than reached through whoever writes it. That is the point of the pair:
:data:`~apps.shared.events.catalog.catalog` and :data:`wiring` are the two halves of what this
process knows about events, and a reader of either imports it directly. A test that needs its own
subscriptions builds ``EventBus(EventWiring())``; a test that must register on the *live* bus — to
exercise the real fan-out — uses :meth:`snapshot` and :meth:`restore` instead.

The bus writes here at mount; the listener reads reactions to deliver off the trail; the console
reads both halves for its event → reaction graph.
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
    """A durable ``bus.on`` consumer of an event type: its ``name`` (the reaction), the queue
    ``topic`` it feeds, and the ``app`` that listens (for the console's event → reaction graph)."""

    name: str
    topic: str
    as_actor: bool
    app: str


@dataclass(frozen=True)
class WiringSnapshot:
    """A copy of a wiring's two halves, deep enough to restore over later mutations — what a test
    fixture holds while it registers on the live bus."""

    owners: dict[type[BusinessEvent], str]
    reactions: dict[type[BusinessEvent], list[Reaction]]
    spread: dict[type[BusinessEvent], list[SpreadHandler]]


class EventWiring:
    """Who emits what, and who reacts to it — this process's mount-time wiring."""

    def __init__(self) -> None:
        self._owner_by_type: dict[type[BusinessEvent], str] = {}
        self._reactions: dict[type[BusinessEvent], list[Reaction]] = {}
        self._spread: dict[type[BusinessEvent], list[SpreadHandler]] = defaultdict(list)

    # ── Ownership: who emits what ────────────────────────────────────────────────────────────

    def declare(self, *event_types: type[BusinessEvent]) -> None:
        """Record that each of ``event_types`` is emitted by the app it names — ``app_name``, read
        off the class. Declaring is therefore only *activation* (this mounted app emits these
        facts), never an attribution: an app cannot claim another's events because it never says
        whose they are. Re-declaring is idempotent.

        An event with no ``app_name``/``verb`` has no kind at all — it never entered the catalog, so
        the listener could not rebuild it from a row. Declaring one is a mistake worth naming
        (typically an abstract base handed over instead of its concrete subclasses)."""
        for event_type in event_types:
            if not event_type.kind:
                raise ValueError(
                    f"{event_type.__name__} declares no app_name/verb, so it has no kind — "
                    "an unnamed fact cannot be persisted or rebuilt"
                )
            self._owner_by_type[event_type] = event_type.app_name

    def is_declared(self, event_type: type[BusinessEvent]) -> bool:
        """Whether some app declared it — the gate ``emit`` checks before persisting a fact."""
        return event_type in self._owner_by_type

    def owner_of(self, event_type: type[BusinessEvent]) -> str | None:
        """The app that declared (emits) this event, or ``None`` if undeclared."""
        return self._owner_by_type.get(event_type)

    def by_app(self) -> dict[str, list[type[BusinessEvent]]]:
        """The declared events grouped by owner app (app name sorted), for the console — each app's
        own vocabulary of "what it emits"."""
        grouped: dict[str, list[type[BusinessEvent]]] = defaultdict(list)
        for event_type, app in self._owner_by_type.items():
            grouped[app].append(event_type)
        return {app: grouped[app] for app in sorted(grouped)}

    # ── Reactions: who listens ───────────────────────────────────────────────────────────────

    def add_consumer(
        self, event_type: type[BusinessEvent], name: str, *, as_actor: bool, app: str
    ) -> str:
        """Register a durable consumer ``name`` (in ``app``) for ``event_type``; return its topic.

        ``name`` must be unique among the event's consumers (the topic ``evt:<kind>:<name>`` keys an
        independent task row per consumer). Raises ``ValueError`` on a duplicate."""
        topic = f"evt:{event_type.kind}:{name}"
        registered = self._reactions.setdefault(event_type, [])
        if any(r.topic == topic for r in registered):
            raise ValueError(f"duplicate consumer {name!r} for {event_type.__name__}")
        registered.append(Reaction(name=name, topic=topic, as_actor=as_actor, app=app))
        return topic

    def consumers_of(self, event_type: type) -> list[Reaction]:
        """All durable consumers keyed on the event's MRO — a base-type subscription catches
        subclasses, mirroring the bus's dispatch. Read by the listener to fan a fact out."""
        collected: list[Reaction] = []
        for klass in event_type.__mro__:
            collected.extend(self._reactions.get(klass, ()))
        return collected

    def reactions(self) -> dict[type[BusinessEvent], list[Reaction]]:
        """Every event type that has a durable consumer, mapped to its consumers — the console's
        event → reaction graph (who reacts to what). Read-only copy."""
        return {event_type: list(rs) for event_type, rs in self._reactions.items()}

    # ── Spread handlers: run everywhere ──────────────────────────────────────────────────────

    def add_spread_handler(self, event_type: type[BusinessEvent], handler: SpreadHandler) -> None:
        """Register a run-everywhere ``spread`` handler for ``event_type`` (config propagation)."""
        self._spread[event_type].append(handler)

    def spread_kinds(self) -> list[str]:
        """The dotted kinds that have a ``spread`` handler — the listener scans the trail for
        exactly these to replay per instance. An abstract base has no kind of its own and drops out
        here; its concrete subclasses carry theirs, and :meth:`spread_handlers_for` walks the MRO
        to reach the handler from them."""
        return [k for t in self._spread if (k := t.kind)]

    def spread_handlers_for(self, event: BusinessEvent) -> Iterator[SpreadHandler]:
        """The ``spread`` handlers registered for the event's runtime type or any base, most-
        specific first, each once — run in-process by the listener off a persisted fact."""
        seen: set[int] = set()
        for klass in type(event).__mro__:
            for handler in self._spread.get(klass, ()):
                if id(handler) not in seen:
                    seen.add(id(handler))
                    yield handler

    # ── Isolation, for a test that must register on the live bus ─────────────────────────────

    def snapshot(self) -> WiringSnapshot:
        """A restorable copy of both halves. A test exercising the *real* fan-out has to register
        on the process-wide bus; this is how it puts back what it found, without reaching into the
        wiring's internals to do it."""
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


# The process's wiring — what the mounted apps declared and subscribed. Imported by everyone who
# reads it (the listener, the console), never reached through the bus that writes it: a reader
# wanting to know who reacts to a fact has no business holding an emitter to find out.
wiring = EventWiring()
