"""How the styleguide context plugs in: mounts the demo router, claims its slug."""

from apps.shared.host import Host
from apps.styleguide.router import router


def mount(host: Host) -> None:
    host.app.include_router(router)
    host.reserve("styleguide")
