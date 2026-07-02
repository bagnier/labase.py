"""How the console context plugs into the running app: mounts the admin router, claims slugs.

Also owns the *bootstrap policy*: the first registered user becomes a server admin. It reacts
to auth's ``UserCreated`` and promotes the user iff the server has no admin yet. The claim lands
in GoTrue before registration redirects to sign-in, so the user's first session carries it.
"""

import uuid
from typing import cast

from apps.auth.contract.admin import count_server_admins, set_server_admin
from apps.auth.contract.events import UserCreated
from apps.settings.contract import appearance
from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.infra.audit_log_repository import AuditLogRepository
from apps.settings.infra.router import router
from apps.shared.host import Host
from apps.shared.http.templates import templates


def mount(host: Host) -> None:
    host.app.include_router(router, prefix="/console")
    host.reserve("console", "admin", "logs")
    host.events.on(UserCreated, _bootstrap_first_admin)
    host.events.on(ConsoleOverviewQuery, _logs_overview)
    appearance.mount(host)
    # Live appearance globals, alongside ``css_v`` — every page reads the app-wide theme.
    jinja_globals = cast("dict[str, object]", templates.env.globals)
    jinja_globals["app_theme"] = appearance.current_theme
    jinja_globals["app_themes"] = lambda: appearance.THEMES


async def _bootstrap_first_admin(event: UserCreated) -> None:
    if await count_server_admins() == 0:
        await set_server_admin(uuid.UUID(event.user_id), True)


async def _logs_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    count = await AuditLogRepository(query.session).count()
    return ConsoleOverview(
        key="logs",
        title="Audit logs",
        icon="scroll",
        data={"lines": [f"{count} events recorded"]},
    )
