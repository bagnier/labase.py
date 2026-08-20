"""How the health context plugs into the running app: mounts the probe router, claims its slug."""

from apps.health.router import router
from apps.shared.integration.host import Host, MountPhase

PHASE = MountPhase.FOUNDATION


def mount(host: Host) -> None:
    host.app.include_router(router)
    host.reserve("health")
