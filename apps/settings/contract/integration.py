"""How the console context plugs into the running app: mounts the admin router, claims slugs.

Also owns the *bootstrap policy*: the first registered user becomes a server admin. It reacts
to auth's ``UserCreated`` and promotes the user iff the server has no admin yet. The claim lands
in GoTrue before registration redirects to sign-in, so the user's first session carries it.
"""

import uuid
from typing import cast

from apps.auth.contract.admin import count_server_admins, set_server_admin
from apps.auth.contract.events import UserCreated
from apps.settings.contract import observability
from apps.settings.contract.appearance import (
    DEFAULT_THEME,
    THEME_APP,
    THEME_KEY,
    THEMES,
    appearance,
    current_theme,
)
from apps.settings.contract.appearance import (
    overview as appearance_overview,
)
from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.contract.settings import SettingDef, SettingsChanged, declare_app_settings
from apps.settings.contract.technical import overview as technical_overview
from apps.settings.infra.audit_log_repository import AuditLogRepository
from apps.settings.infra.refresh import SettingsRefresher
from apps.settings.infra.router import router
from apps.shared.config import get_technical_settings
from apps.shared.host import Host
from apps.shared.http.templates import templates


def mount(host: Host) -> None:
    host.app.include_router(router, prefix="/console")
    host.reserve("console", "admin", "logs", "settings")
    host.events.on(UserCreated, _bootstrap_first_admin)
    host.events.on(ConsoleOverviewQuery, _logs_overview)

    appearance.group = declare_app_settings(
        THEME_APP,
        defs=[
            SettingDef(
                THEME_KEY,
                "string",
                DEFAULT_THEME,
                "Application theme — applies to everyone (one of the enabled DaisyUI themes)",
            )
        ],
    )
    appearance.read()
    host.events.on(SettingsChanged, appearance.reload)
    host.events.on(ConsoleOverviewQuery, appearance_overview)

    observability.declare()
    host.events.on(SettingsChanged, observability.reload)
    host.events.on(ConsoleOverviewQuery, observability.overview)

    host.events.on(ConsoleOverviewQuery, technical_overview)

    # With N instances only the one handling the console POST reloads in-process;
    # the others converge within one TTL through this per-process re-read loop.
    refresher = SettingsRefresher(host, get_technical_settings().settings_refresh_seconds)
    host.events.on(SettingsChanged, refresher.absorb)
    host.app.router.add_event_handler("startup", refresher.start)
    host.app.router.add_event_handler("shutdown", refresher.stop)

    # Live appearance globals, alongside ``css_v`` — every page reads the app-wide theme.
    jinja_globals = cast("dict[str, object]", templates.env.globals)
    jinja_globals["app_theme"] = current_theme
    jinja_globals["app_themes"] = lambda: THEMES


async def _bootstrap_first_admin(event: UserCreated) -> None:
    if await count_server_admins() == 0:
        await set_server_admin(uuid.UUID(event.user_id), True)


async def _logs_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    count = await AuditLogRepository(query.session).count()
    return ConsoleOverview(
        key="logs",
        title="Audit logs",
        icon="scroll",
        group="settings",
        data={"lines": [f"{count} events recorded"]},
    )
