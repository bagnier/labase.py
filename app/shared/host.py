"""Host — the app-wide wiring object passed to every context's register(app, host).

Carries the event bus and the reserved-slug registry. ``host`` is the production singleton;
tests can build a fresh :class:`Host` in isolation.
"""

from dataclasses import dataclass, field

from app.shared.bus import EventBus
from app.shared.slug_registry import reserve as _reserve_slugs


@dataclass
class Host:
    events: EventBus = field(default_factory=EventBus)

    def reserve(self, *slugs: str) -> None:
        """Claim URL slugs so no org handle can shadow them (see :mod:`app.shared.names`)."""
        _reserve_slugs(*slugs)


host = Host()
