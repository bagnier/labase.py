"""How the console context plugs into the running app: mounts the admin router, claims slugs.

Also owns the *bootstrap policy*: the first registered user becomes a server admin. It reacts
to auth's ``UserCreated`` and promotes the user iff the server has no admin yet. The claim lands
in GoTrue before registration redirects to sign-in, so the user's first session carries it.
"""

import uuid

from apps.auth.contract.admin import count_server_admins, set_server_admin
from apps.auth.contract.events import UserCreated
from apps.settings.infra.router import router
from apps.shared.host import Host


def mount(host: Host) -> None:
    host.app.include_router(router, prefix="/console")
    host.reserve("console", "admin")
    host.events.on(UserCreated, _bootstrap_first_admin)


async def _bootstrap_first_admin(event: UserCreated) -> None:
    if await count_server_admins() == 0:
        await set_server_admin(uuid.UUID(event.user_id), True)
