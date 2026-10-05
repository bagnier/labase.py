"""The :class:`Host` every context's ``mount(host)`` receives. :data:`host` is the production one;
a test builds a fresh ``Host()``, isolated from the process's event wiring and contribs.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Protocol

import structlog
from fastapi import FastAPI

from apps.shared.events import BusinessEvent
from apps.shared.events.bus import EventBus, events
from apps.shared.events.wiring import EventWiring
from apps.shared.integration.contribs import Contribs, contribs
from apps.shared.integration.slugs import OpenListChecker
from apps.shared.integration.slugs import register_open_list as _register_open_list
from apps.shared.integration.slugs import reserve as _reserve_slugs
from apps.shared.logs.capture import drain_once
from apps.shared.settings.live import (
    AppSettings,
    SettingsChanged,
    SettingsDeclaration,
    bind_settings,
)
from apps.shared.vocabulary import PhosphorIcon

if TYPE_CHECKING:
    from apps.shared.integration.fullpage import FullpageQuery

log = structlog.get_logger(__name__)

_Registrations = Sequence[tuple[type, Callable[[Any], Awaitable[Any]]]]


class LifespanTask(Protocol):
    """A background worker: ``start`` is idempotent; ``stop`` cancels, awaits, and drains once
    more what it holds in memory, since every deploy ends the process with SIGTERM. A worker
    reading Postgres (task worker, event listener) has nothing to drain.
    """

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class MountPhase(IntEnum):
    """When a context mounts: FastAPI matches routes in registration order, so a catch-all must
    come after every fixed prefix it could shadow. Each context declares its ``PHASE``; the
    composition root sorts on it, ties keeping their listing order."""

    FOUNDATION = 0  # fixed prefixes only (/auth, /profile, /health, static)
    CONSOLE_SCREEN = 1  # fixed /console/<x> routers — before the console's catch-all
    CONSOLE = 2  # the console's /console/{app} catch-all
    ORG = 3  # /{org_handle}/… catch-alls
    PUBLIC = 4  # the single-segment /{slug} catch-all — last


@dataclass(frozen=True)
class AppManifest:
    """Everything a standard org app contributes, mounted by :meth:`Host.register_app`. An app
    needing more (startup hooks, fullpage providers, open lists) writes its own ``mount()``.

    ``provides`` stays live when the app is disabled (its console tile, so an admin can switch it
    back on); everything else exists only when enabled. ``consumes_when_enabled`` are durable
    consumers run on the admin session, idempotent (welcome seeding).
    """

    settings: SettingsDeclaration
    provides: _Registrations = ()
    routers: Sequence[tuple[Any, str]] = ()  # (APIRouter, prefix)
    nav: Sequence[NavItem] = ()
    provides_when_enabled: _Registrations = ()
    emits: Sequence[type[BusinessEvent]] = ()
    consumes_when_enabled: Sequence[
        tuple[type[BusinessEvent], str, Callable[..., Awaitable[None]]]
    ] = ()
    reserve: Sequence[str] = ()  # see Host.reserve


@dataclass(frozen=True)
class NavItem:
    """A sidebar link, registered only while its app is enabled."""

    label: str
    icon: PhosphorIcon
    segment: str  # after /{org_handle}/, e.g. "learning/sessions"
    match: str  # a request path containing it marks the link active, e.g. "/todos"
    order: int = 50  # lower comes first
    owner_only: bool = False


@dataclass(frozen=True)
class FullpageProvider:
    """A slice of the full-page context (see :mod:`apps.shared.integration.fullpage`). ``keys``
    are what ``fn`` returns, declared so collisions are caught at mount."""

    name: str
    keys: frozenset[str]
    fn: Callable[[FullpageQuery], Awaitable[dict]]


# Seeded by :func:`~apps.shared.integration.fullpage.fullpage_context` itself.
RESERVED_FULLPAGE_KEYS: frozenset[str] = frozenset({"user", "nav_items"})


@dataclass
class Host:
    app: FastAPI = field(default_factory=lambda: FastAPI(title="labase"))
    # A bare Host (a test) gets its own wiring; the event catalog stays process-wide.
    events: EventBus = field(default_factory=lambda: EventBus(EventWiring()))
    contribs: Contribs = field(default_factory=Contribs)
    nav_items: list[NavItem] = field(default_factory=list)
    fullpage_providers: list[FullpageProvider] = field(default_factory=list)
    # Keyed by declared group, which may differ from the app: auth declares "users".
    settings_handles: dict[str, AppSettings] = field(default_factory=dict)

    def reserve(self, *slugs: str) -> None:
        """Claim URL slugs no org handle may take. An app reserves exactly the top-level paths it
        routes (``/files/share/…``, ``/metrics``); routes under ``/{org_handle}/`` need none."""
        _reserve_slugs(*slugs)

    def register_open_list(self, name: str, checker: OpenListChecker) -> None:
        """Register a context's handle namespace for cross-context uniqueness."""
        _register_open_list(name, checker)

    def register_app(self, manifest: AppManifest) -> AppSettings:
        """Mount a standard app; returns its live settings handle."""
        for query_type, provider in manifest.provides:
            self.contribs.provide(query_type, provider)
        settings = self.register_settings(manifest.settings)
        self.reserve(*manifest.reserve)
        if not settings.enabled:
            return settings
        for router, prefix in manifest.routers:
            self.app.include_router(router, prefix=prefix)
        for item in manifest.nav:
            self.register_nav(item)
        self.events.declare(*manifest.emits)
        for event_type, name, consumer in manifest.consumes_when_enabled:
            self.events.on(
                event_type,
                consumer,
                name=name,
                app=manifest.settings.app_name,
                as_actor=False,
                idempotent=True,
            )
        for query_type, provider in manifest.provides_when_enabled:
            self.contribs.provide(query_type, provider)
        return settings

    def register_nav(self, item: NavItem) -> None:
        self.nav_items.append(item)

    def register_fullpage_provider(
        self, name: str, keys: Sequence[str], fn: Callable[[FullpageQuery], Awaitable[dict]]
    ) -> None:
        """Register a full-page slice. Raises ``ValueError`` on a taken ``name`` or a namespaced
        key already claimed, rather than overwriting it on every render."""
        if any(existing.name == name for existing in self.fullpage_providers):
            raise ValueError(
                f"fullpage provider {name!r} is already registered — "
                "two providers under the same name would collide on every render"
            )
        namespaced = {f"{name}_{key}" for key in keys}
        claimed = RESERVED_FULLPAGE_KEYS | {
            f"{existing.name}_{key}"
            for existing in self.fullpage_providers
            for key in existing.keys
        }
        collision = sorted(namespaced & claimed)
        if collision:
            raise ValueError(
                f"fullpage provider {name!r} would collide on {collision} — "
                "already claimed by another provider or by the host-seeded context"
            )
        self.fullpage_providers.append(FullpageProvider(name, frozenset(keys), fn))

    def on_startup(self, handler: Callable[[], Awaitable[None]]) -> None:
        """Register an async startup hook; a failing one is reported (see :func:`_reported`)."""
        self.app.router.add_event_handler("startup", _reported(handler))

    def run_background(self, task: LifespanTask) -> None:
        """Start ``task`` at startup and stop it at shutdown."""
        self.on_startup(task.start)
        self.on_shutdown(task.stop)

    def on_shutdown(self, handler: Callable[[], Awaitable[None]]) -> None:
        self.app.router.add_event_handler("shutdown", handler)

    def register_settings(self, declaration: SettingsDeclaration) -> AppSettings:
        """Seed and load an app's settings, expose them to the console and
        :func:`~apps.shared.settings.live.get_settings`, and keep them live on
        :class:`SettingsChanged`. Returns the handle."""
        settings = bind_settings(declaration)
        self.settings_handles[declaration.app_name] = settings
        self.events.spread(SettingsChanged, settings.reload)
        return settings

    def declared_settings(self, app: str) -> SettingsDeclaration | None:
        handle = self.settings_handles.get(app)
        return handle.declaration if handle is not None else None


def _reported(handler: Callable[[], Awaitable[None]]) -> Callable[[], Awaitable[None]]:
    """Wrap a startup hook so a failure still opens an issue, then fails the boot.

    The ``CaptureDrain`` is itself a startup hook and may never run, so the queue is drained here;
    the trackers subscribed at mount, and the loop is up.
    """

    @functools.wraps(handler)
    async def guarded() -> None:
        try:
            await handler()
        except Exception as exc:
            log.exception(
                "host.startup_failed",
                exc_info=exc,
                hook=getattr(handler, "__qualname__", repr(handler)),
            )
            await drain_once()
            raise

    return guarded


# Mount-time registrations and runtime calls share the process-wide bus and contribs.
host = Host(events=events, contribs=contribs)
