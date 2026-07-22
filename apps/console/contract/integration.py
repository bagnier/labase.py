"""How the console context plugs into the running app: mounts the admin router, claims slugs.

Also owns the *bootstrap policy*: the first registered user becomes a server admin. It reacts
to auth's ``UserCreated`` and promotes the user iff the server has no admin yet. The claim lands
in GoTrue before registration redirects to sign-in, so the user's first session carries it.
"""

import uuid
from typing import cast

from apps.auth.contract.admin import count_server_admins, set_server_admin
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
from apps.console.contract.overviews import ConsoleOverviewQuery
from apps.console.contract.technical import overview as technical_overview
from apps.console.infra.router import router
from apps.shared.host import Host, MountPhase
from apps.shared.http.templates import templates
from apps.shared.settings import SettingDef, SettingsDeclaration

PHASE = MountPhase.CONSOLE


def mount(host: Host) -> None:
    host.app.include_router(router, prefix="/console")
    host.reserve("console", "admin", "logs", "settings")
    host.events.on(UserCreated, _bootstrap_first_admin)

    host.register_settings(_declare_appearance_settings())
    host.contribs.provide(ConsoleOverviewQuery, appearance_overview)

    host.contribs.provide(ConsoleOverviewQuery, technical_overview)

    # Settings live-reload rides the event tailer: a persisted ``SettingsChanged`` is replayed to
    # each process's ``spread`` handler (``settings.reload``) off the trail — no per-app re-read
    # loop here (see ``host.register_settings`` + ``apps.shared.events.listener``).

    # Live appearance globals, alongside ``asset`` — every page reads the app-wide theme.
    jinja_globals = cast("dict[str, object]", templates.env.globals)
    jinja_globals["app_theme"] = current_theme
    jinja_globals["app_themes"] = lambda: THEMES


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


async def _bootstrap_first_admin(event: UserCreated) -> None:
    if await count_server_admins() == 0:
        await set_server_admin(uuid.UUID(event.actor_id), True)
