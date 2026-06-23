"""How the health context plugs into the running app: mounts the probe router, claims its slug."""

from fastapi import FastAPI

from apps.health.router import router
from apps.shared.host import Host


def mount(app: FastAPI, host: Host) -> None:
    app.include_router(router)
    host.reserve("health")
