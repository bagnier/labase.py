"""Host — the app-wide wiring object passed to every context's mount(app, host).

Carries the event bus and the reserved-slug registry. ``host`` is the production singleton;
tests can build a fresh :class:`Host` in isolation.
"""

from dataclasses import dataclass, field

from app.shared.bus import EventBus
from app.shared.slug_registry import reserve as _reserve_slugs


@dataclass(frozen=True)
class NavItem:
    """A sidebar link an app contributes from its :func:`mount`.

    Registered only when the app is enabled (apps' ``mount`` short-circuits when disabled),
    so a link appears iff its app is switched on. ``segment`` is appended to ``/{org_handle}/``.
    """

    label: str
    icon: str  # phosphor icon name, e.g. "clipboard-text"
    segment: str  # path relative to the org, e.g. "todos", "learning/sessions"
    match: str  # substring of request path marking the link active, e.g. "/todos"
    order: int = 50  # display order; lower comes first
    owner_only: bool = False  # only show to org owners


@dataclass
class Host:
    events: EventBus = field(default_factory=EventBus)
    nav_items: list[NavItem] = field(default_factory=list)

    def reserve(self, *slugs: str) -> None:
        """Claim URL slugs so no org handle can shadow them (see :mod:`app.shared.names`)."""
        _reserve_slugs(*slugs)

    def register_nav(self, item: NavItem) -> None:
        """Add a sidebar link, contributed by an app from its :func:`mount`."""
        self.nav_items.append(item)


host = Host()
