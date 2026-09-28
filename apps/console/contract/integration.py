"""How the console context plugs into the running app: mounts the admin router, claims slugs.

Also owns the *bootstrap policy*: the first registered user becomes a server admin. It reacts
to auth's ``UserCreated`` (a durable consumer, run off the journal after commit) and promotes the
user iff the server has no admin yet. The claim lands in GoTrue shortly after registration; a
signed-in session picks it up on its next token mint (tests drive the listener to make this
deterministic).
"""

from typing import cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from supabase_auth.errors import AuthApiError

from apps.auth.contract.admin import list_server_admins, set_server_admin
from apps.auth.contract.events import UserCreated
from apps.console.contract.appearance import (
    DEFAULT_THEME,
    THEME_APP,
    THEME_KEY,
    THEMES,
    current_theme,
)
from apps.console.contract.appearance import (
    overview as appearance_overview,
)
from apps.console.contract.events import (
    AdminGranted,
    AdminRevoked,
    OrgOverrideRemoved,
    OrgOverrideSet,
)
from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.console.contract.technical import overview as technical_overview
from apps.console.infra.router import router
from apps.shared.events.wiring import wiring
from apps.shared.http.templates import templates
from apps.shared.integration.host import Host, MountPhase
from apps.shared.settings.live import SettingDef, SettingsChanged, SettingsDeclaration

PHASE = MountPhase.CONSOLE

log = structlog.get_logger(__name__)


def mount(host: Host) -> None:
    host.app.include_router(router, prefix="/console")
    host.reserve("console", "admin", "timeline", "settings")
    # The console owns the ``settings.*`` namespace: the platform-admin actions plus the
    # server-wide settings-change fact it emits when an admin edits a setting.
    host.events.declare(
        SettingsChanged,
        AdminGranted,
        AdminRevoked,
        OrgOverrideSet,
        OrgOverrideRemoved,
    )
    host.events.on(
        UserCreated, _bootstrap_first_admin, name="bootstrap_first_admin", app="settings"
    )

    host.register_settings(_declare_appearance_settings())
    host.contribs.provide(ConsoleOverviewQuery, appearance_overview)
    host.contribs.provide(ConsoleOverviewQuery, _events_overview)

    host.contribs.provide(ConsoleOverviewQuery, technical_overview)

    # Settings live-reload rides the event listener: a persisted ``SettingsChanged`` is replayed to
    # each process's ``spread`` handler (``settings.reload``) off the journal — no per-app re-read
    # loop here (see ``host.register_settings`` + ``apps.shared.events.listener``).

    # Live appearance globals, alongside ``asset`` — every page reads the app-wide theme.
    jinja_globals = cast("dict[str, object]", templates.env.globals)
    jinja_globals["app_theme"] = current_theme
    jinja_globals["app_themes"] = lambda: THEMES


async def _events_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    """Console tile → the event → reaction graph: how many events the system emits, and how many
    durable reactions wire them together. Read straight from the wiring (no DB)."""
    emitted = sum(len(declared) for declared in wiring.by_app().values())
    reactions = sum(len(rs) for rs in wiring.reactions().values())
    return ConsoleOverview(
        key="events",
        title="Events",
        icon="lightning",
        section="operations",
        href="/console/events",
        data={"lines": [f"{emitted} events", f"{reactions} reactions"]},
    )


def _declare_appearance_settings() -> SettingsDeclaration:
    return SettingsDeclaration(
        app_name=THEME_APP,
        defs=[
            SettingDef(
                THEME_KEY,
                "string",
                DEFAULT_THEME,
                "Application theme — applies to everyone (one of the enabled DaisyUI themes)",
            )
        ],
    )


async def _bootstrap_first_admin(session: AsyncSession, event: UserCreated) -> None:
    # Durable consumer of UserCreated; runs on the GoTrue admin API, not ``session``.
    # UserCreated is an immutable fact: by delivery the actor may be hard-deleted (gone from the
    # directory) or soft-deleted (a tombstone the directory's live listing excludes). Only a user
    # the admin count would see may be promoted — a claim on a tombstone counts for nothing, so
    # the count stays at zero and every following fact promotes another. One listing answers both
    # questions.
    if event.user_id is None:
        return
    directory = await list_server_admins()
    if any(u.is_admin for u in directory):
        return
    if all(u.user_id != event.user_id for u in directory):
        log.info("bootstrap_first_admin.actor_gone", user_id=event.user_id)
        return
    try:
        await set_server_admin(event.user_id, is_admin=True)
    except AuthApiError:
        # The race remains: hard-deleted between the listing and the write is a clean 404 no-op.
        log.info("bootstrap_first_admin.actor_gone", user_id=event.user_id)
