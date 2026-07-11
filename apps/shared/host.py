"""Host — the app-wide wiring object passed to every context's mount(host).

Carries the FastAPI app, the event bus and the reserved-slug registry. ``host`` is the
production singleton; tests can build a fresh :class:`Host` in isolation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import FastAPI

from apps.shared.bus import EventBus, bus
from apps.shared.settings import (
    AppSettings,
    ConsoleLink,
    SettingsChanged,
    SettingsDeclaration,
    bind_settings,
)
from apps.shared.slug_registry import OpenListChecker
from apps.shared.slug_registry import register_open_list as _register_open_list
from apps.shared.slug_registry import reserve as _reserve_slugs

if TYPE_CHECKING:
    from apps.shared.page import FullpageQuery


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


@dataclass(frozen=True)
class FullpageProvider:
    """A fullpage-context slice an app contributes from its :func:`mount`.

    ``fn`` produces a ``dict`` from a :class:`~apps.shared.page.FullpageQuery`; each key
    it returns is namespaced as ``f"{name}_{key}"`` (e.g. name ``profile`` returning
    ``handle`` lands in the context as ``profile_handle``).
    """

    name: str
    fn: Callable[[FullpageQuery], Awaitable[dict]]


@dataclass
class Host:
    app: FastAPI = field(default_factory=lambda: FastAPI(title="labase"))
    events: EventBus = field(default_factory=EventBus)
    nav_items: list[NavItem] = field(default_factory=list)
    fullpage_providers: list[FullpageProvider] = field(default_factory=list)
    # The live settings handles of this composition, by declared group name (an app may
    # declare under a name meant for admins: auth declares "users", console "appearance").
    # The declaration itself lives on the handle — one source of truth, no parallel dict.
    settings_handles: dict[str, AppSettings] = field(default_factory=dict)

    def reserve(self, *slugs: str) -> None:
        """Claim URL slugs so no org handle can shadow them
        (see :mod:`apps.shared.slug_registry`).

        One rule: an app reserves a slug iff it routes that *top-level* path
        (``/files/share/…``, ``/metrics``). Org-scoped routers live under
        ``/{org_handle}/…`` where no handle can shadow them — nothing to reserve."""
        _reserve_slugs(*slugs)

    def register_open_list(self, name: str, checker: OpenListChecker) -> None:
        """Register a handle namespace to check for cross-context slug uniqueness
        (see :mod:`apps.shared.slug_registry`) — the flip side of :meth:`reserve`,
        routed through the host so mounts touch one slug surface."""
        _register_open_list(name, checker)

    def register_nav(self, item: NavItem) -> None:
        """Add a sidebar link, contributed by an app from its :func:`mount`."""
        self.nav_items.append(item)

    def register_fullpage_provider(
        self, name: str, fn: Callable[[FullpageQuery], Awaitable[dict]]
    ) -> None:
        """Register a fullpage-context slice, contributed by an app from its :func:`mount`."""
        self.fullpage_providers.append(FullpageProvider(name, fn))

    def on_startup(self, handler: Callable[[], Awaitable[None]]) -> None:
        """Register an async startup hook from an app's :func:`mount`.

        Routed through the host so apps never touch ``host.app.router`` or FastAPI's lifespan
        directly — used by the recurring-task planters, task workers and metrics flushers."""
        self.app.router.add_event_handler("startup", handler)

    def on_shutdown(self, handler: Callable[[], Awaitable[None]]) -> None:
        """Register an async shutdown hook, contributed by an app from its :func:`mount`."""
        self.app.router.add_event_handler("shutdown", handler)

    def register_settings(self, declaration: SettingsDeclaration) -> AppSettings:
        """Bring an app's settings live in one call from ``mount()``: record the declaration for
        the console to render, seed and read values, register the handle in the process registry
        (:func:`~apps.shared.settings.get_settings`), and subscribe it to :class:`SettingsChanged`.
        Returns the live handle, so ``if not settings.enabled`` works immediately."""
        settings = bind_settings(declaration)
        self.settings_handles[declaration.app_name] = settings
        self.events.on(SettingsChanged, settings.reload)
        return settings

    def declared_settings(self, app: str) -> SettingsDeclaration | None:
        """The metadata ``app`` declared at mount, or ``None`` if it declared none."""
        handle = self.settings_handles.get(app)
        return handle.declaration if handle is not None else None

    def declared_console_links(self) -> list[ConsoleLink]:
        """Every console screen declared by mounted apps — the console overview renders them."""
        return [
            link
            for handle in self.settings_handles.values()
            if handle.declaration is not None
            for link in handle.declaration.links
        ]


# Production singleton: share the process-wide event bus so runtime ``bus.emit/collect`` and
# these mount-time ``host.events.on(...)`` registrations hit one registry. A bare ``Host()``
# (e.g. in a test) still gets its own isolated bus via the field default.
host = Host(events=bus)
