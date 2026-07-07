"""Host — the app-wide wiring object passed to every context's mount(host).

Carries the FastAPI app, the event bus and the reserved-slug registry. ``host`` is the
production singleton; tests can build a fresh :class:`Host` in isolation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fastapi import FastAPI

from apps.shared.bus import EventBus
from apps.shared.settings import (
    AppSettings,
    ConsoleLink,
    SettingsChanged,
    SettingsDeclaration,
    bind_settings,
)
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
    declarations: dict[str, SettingsDeclaration] = field(default_factory=dict)

    def reserve(self, *slugs: str) -> None:
        """Claim URL slugs so no org handle can shadow them (see :mod:`apps.shared.names`)."""
        _reserve_slugs(*slugs)

    def register_nav(self, item: NavItem) -> None:
        """Add a sidebar link, contributed by an app from its :func:`mount`."""
        self.nav_items.append(item)

    def register_fullpage_provider(
        self, name: str, fn: Callable[[FullpageQuery], Awaitable[dict]]
    ) -> None:
        """Register a fullpage-context slice, contributed by an app from its :func:`mount`."""
        self.fullpage_providers.append(FullpageProvider(name, fn))

    def register_settings(self, declaration: SettingsDeclaration) -> AppSettings:
        """Bring an app's settings live in one call: register ``declaration`` (the console admin
        page reads it back through :meth:`declared_settings`/:meth:`declared_console_links`),
        then :func:`apps.shared.settings.bind_settings` seeds missing values, reads current ones
        and registers the handle in the process registry
        (:func:`~apps.shared.settings.get_settings`), and this subscribes it to
        :class:`SettingsChanged`. Returns the live handle, so ``if not settings.enabled`` works
        right after this call."""
        self.declarations[declaration.app_name] = declaration
        settings = bind_settings(declaration)
        self.events.on(SettingsChanged, settings.reload)
        return settings

    def declared_settings(self, app: str) -> SettingsDeclaration | None:
        """The metadata ``app`` declared at mount, or ``None`` if it declared none."""
        return self.declarations.get(app)

    def declared_console_links(self) -> list[ConsoleLink]:
        """Every console screen declared by mounted apps — the console overview renders them."""
        return [link for d in self.declarations.values() for link in d.links]


host = Host()
