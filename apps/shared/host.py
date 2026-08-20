"""Host — the app-wide wiring object passed to every context's mount(host).

Carries the FastAPI app, the event bus and the reserved-slug registry. ``host`` is the
production singleton; tests can build a fresh :class:`Host` in isolation.
"""

from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Protocol

import structlog
from fastapi import FastAPI

from apps.shared.contribs import Contribs, contribs
from apps.shared.events import BusinessEvent
from apps.shared.events.bus import EventBus, events
from apps.shared.events.wiring import EventWiring
from apps.shared.logs.capture import drain_once
from apps.shared.settings import (
    AppSettings,
    SettingsChanged,
    SettingsDeclaration,
    bind_settings,
)
from apps.shared.slug_registry import OpenListChecker
from apps.shared.slug_registry import register_open_list as _register_open_list
from apps.shared.slug_registry import reserve as _reserve_slugs
from apps.shared.vocabulary import PhosphorIcon

if TYPE_CHECKING:
    from apps.shared.page import FullpageQuery

log = structlog.get_logger(__name__)

# The ``(query type, provider)`` pairs an app declares at mount, for the contribs registry.
_Registrations = Sequence[tuple[type, Callable[[Any], Awaitable[Any]]]]


class LifespanTask(Protocol):
    """What every background worker of the base looks like from the outside.

    Five of them exist — the task worker, the event listener, the log drain, the metrics
    flusher, the capture drain — and they agree on exactly this much: ``start`` is idempotent,
    ``stop`` cancels, awaits, **and drains once more**. What each does per tick is its own
    business — the log drain batches to Postgres and falls back to disk when it cannot. This
    states the shared half so
    :meth:`Host.run_background` can take any of them, and so a new one cannot drift into a
    different lifecycle by accident.

    The final drain is the half that is easy to leave out, and the one a deploy makes routine:
    SIGTERM is how every process ends, so whatever a worker is holding at that moment is the
    *normal* amount to lose — the last exceptions before a restart, the traffic since the last
    flush. A worker whose queue is durable elsewhere (the task worker and the event listener read
    Postgres, which keeps their work across the restart) has nothing to drain and simply stops.
    """

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class MountPhase(IntEnum):
    """Route-registration order classes — FastAPI matches routes in registration order,
    so catch-alls must come after every fixed prefix they could shadow. Each context's
    ``integration`` module declares its ``PHASE``; the composition root sorts by it
    (stable, so ties keep their listing order) instead of hand-ordering a tuple."""

    FOUNDATION = 0  # fixed prefixes only (/auth, /profile, /health, static)
    CONSOLE_SCREEN = 1  # fixed /console/<x> routers — before the console's catch-all
    CONSOLE = 2  # the console's /console/{app} catch-all
    ORG = 3  # /{org_handle}/… catch-alls
    PUBLIC = 4  # the single-segment /{slug} catch-all — last


@dataclass(frozen=True)
class AppManifest:
    """Everything a standard org app contributes, declared as one object.

    :meth:`Host.register_app` walks it in the one correct order, so each app stops
    re-spelling the mount ceremony — including the trap that the console tile must
    register *before* the enabled gate (a disabled app still shows its tile, which is
    how an admin re-enables it). ``provides`` contributions live even when the app is
    disabled (the console tile is such a contribution); everything else only exists when
    it is enabled. Apps with needs beyond this shape
    (startup hooks, fullpage providers, open lists) keep an explicit ``mount()``.

    ``emits`` names the events this app owns and may emit (see :meth:`Host.events.declare`);
    ``consumes_when_enabled`` its durable async consumers, which the listener runs on the admin
    session, idempotent — the shape a server-owned reaction (welcome seeding) needs to be
    retryable and to stay off the emitting request's path.
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
    reserve: Sequence[str] = ()  # top-level slugs the app routes (see Host.reserve)


@dataclass(frozen=True)
class NavItem:
    """A sidebar link an app contributes from its :func:`mount`.

    Registered only when the app is enabled (apps' ``mount`` short-circuits when disabled),
    so a link appears iff its app is switched on. ``segment`` is appended to ``/{org_handle}/``.
    """

    label: str
    icon: PhosphorIcon
    segment: str  # relative to the org, e.g. "todos", "learning/sessions"
    match: str  # substring of the request path marking the link active, e.g. "/todos"
    order: int = 50  # lower comes first
    owner_only: bool = False


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
    # A bare Host (a test) gets a bus on a wiring of its own, so what it mounts never lands in the
    # process's — what events *exist* is process-wide either way (the catalog).
    events: EventBus = field(default_factory=lambda: EventBus(EventWiring()))
    contribs: Contribs = field(default_factory=Contribs)
    nav_items: list[NavItem] = field(default_factory=list)
    fullpage_providers: list[FullpageProvider] = field(default_factory=list)
    # Keyed by *declared group* name, which an app may aim at admins rather than at itself:
    # auth declares "users", console "appearance".
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

    def register_app(self, manifest: AppManifest) -> AppSettings:
        """Mount a standard app from its :class:`AppManifest`, in the one correct order:
        disabled-safe subscriptions first (console tile), then settings + the enabled
        gate, then routers, nav and enabled-only subscriptions. Returns the live
        settings handle, like :meth:`register_settings`."""
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
        directly — used by the recurring-task planters, task workers and metrics flushers. That
        one seam is also what lets a boot failure be *seen*: see :func:`_reported`."""
        self.app.router.add_event_handler("startup", _reported(handler))

    def run_background(self, task: LifespanTask) -> None:
        """Run ``task`` for the life of the app — the two halves registered together.

        Registering them by hand is how a worker ends up started and never stopped: nothing
        fails, the task simply outlives its shutdown and holds a pool open."""
        self.on_startup(task.start)
        self.on_shutdown(task.stop)

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
        self.events.spread(SettingsChanged, settings.reload)
        return settings

    def declared_settings(self, app: str) -> SettingsDeclaration | None:
        """The metadata ``app`` declared at mount, or ``None`` if it declared none."""
        handle = self.settings_handles.get(app)
        return handle.declaration if handle is not None else None


def _reported(handler: Callable[[], Awaitable[None]]) -> Callable[[], Awaitable[None]]:
    """Wrap a startup hook so a boot it kills leaves an issue behind, then still kills it.

    A startup that raises is the one failure the capture seam could not deliver. The exception
    reaches the chain and lands in the capture queue — but the ``CaptureDrain`` that would fold it
    into an issue is itself a startup hook, and by then nothing more will run. So the queue died
    with the process, and a server that refused to boot said it only on a console nobody kept.

    Draining here works because of *when* it is: the loop is up, and the trackers subscribed at
    **mount**, not at startup — so whichever hook failed, there is someone to hand the exception
    to. That is the difference with a dying interpreter, which keeps its line and gets no issue on
    purpose (``logs.chain``): there, no loop and no pool are left to reach a store on.

    The exception is re-raised: a hook that failed must still fail the boot. Nothing about the
    outcome changes — only that it stops being silent.
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


# The production composition: the process-wide registries, so runtime ``events.emit`` /
# ``contribs.collect`` and mount-time ``host.events.on(...)`` / ``host.contribs.provide(...)`` hit
# one registry each. A bare ``Host()`` still gets its own isolated pair from the field defaults.
host = Host(events=events, contribs=contribs)
