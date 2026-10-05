"""The console mount, and the first-admin bootstrap (AGENTS: the first to sign up is admin): a
``UserCreated`` consumer promoting the user while the server has no admin. The role reaches the
user's token at its next mint.
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
    # ``settings.*``: admin actions and server-wide setting changes.
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

    jinja_globals = cast("dict[str, object]", templates.env.globals)
    jinja_globals["app_theme"] = current_theme
    jinja_globals["app_themes"] = lambda: THEMES


async def _events_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    """The events tile: event and reaction counts, from the wiring."""
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
    # On the GoTrue admin API, not ``session``. By delivery the user may be deleted: only one the
    # admin count sees may be promoted, or the count stays zero and every next signup is promoted.
    if event.user_id is None:
        return
    directory = await list_server_admins()
    if any(u.can_act for u in directory):
        return
    if all(u.user_id != event.user_id for u in directory):
        log.info("bootstrap_first_admin.actor_gone", user_id=event.user_id)
        return
    try:
        await set_server_admin(event.user_id, is_admin=True)
    except AuthApiError:
        # Deleted between listing and write: a clean 404 no-op.
        log.info("bootstrap_first_admin.actor_gone", user_id=event.user_id)
