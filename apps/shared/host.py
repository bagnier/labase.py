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
from apps.shared.slug_registry import reserve as _reserve_slugs

if TYPE_CHECKING:
    from apps.shared.page import PageContextQuery

#: Page-context keys owned by the collector itself; no provider may declare them.
RESERVED_PAGE_KEYS = ("user", "nav_items")


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
class PageContextProvider:
    """A page-context slice an app contributes from its :func:`mount`.

    ``namespace`` is the key prefix the slice owns: every key in ``keys`` must start
    with ``f"{namespace}_"`` (e.g. namespace ``profile`` → key ``profile_handle``).
    ``fn`` produces the slice ``dict`` from a :class:`~apps.shared.page.PageContextQuery`.
    """

    namespace: str
    keys: tuple[str, ...]
    fn: Callable[[PageContextQuery], Awaitable[dict]]


@dataclass
class Host:
    app: FastAPI = field(default_factory=lambda: FastAPI(title="labase"))
    events: EventBus = field(default_factory=EventBus)
    nav_items: list[NavItem] = field(default_factory=list)
    page_providers: list[PageContextProvider] = field(default_factory=list)

    def reserve(self, *slugs: str) -> None:
        """Claim URL slugs so no org handle can shadow them (see :mod:`apps.shared.names`)."""
        _reserve_slugs(*slugs)

    def register_nav(self, item: NavItem) -> None:
        """Add a sidebar link, contributed by an app from its :func:`mount`."""
        self.nav_items.append(item)

    def register_page_context(
        self,
        namespace: str,
        keys: tuple[str, ...],
        fn: Callable[[PageContextQuery], Awaitable[dict]],
    ) -> None:
        """Register a page-context slice, failing fast at startup on a bad key.

        ``namespace`` is the key prefix: every declared key must start with
        ``f"{namespace}_"``. Raises :class:`ValueError` if a key is mis-prefixed,
        reserved, or already owned by another provider.
        """
        claimed = {k: "(reserved)" for k in RESERVED_PAGE_KEYS}
        for p in self.page_providers:
            claimed.update(dict.fromkeys(p.keys, p.namespace))
        for key in keys:
            if not key.startswith(f"{namespace}_"):
                raise ValueError(
                    f"page context key {key!r} must be prefixed by its namespace {namespace!r}_"
                )
            if key in claimed:
                raise ValueError(
                    f"page context key collision: namespace {namespace!r} claims {key!r}, "
                    f"already owned by {claimed[key]!r}"
                )
        self.page_providers.append(PageContextProvider(namespace, tuple(keys), fn))


host = Host()
