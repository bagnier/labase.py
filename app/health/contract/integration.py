"""How the health context plugs into the running app: mounts the probe router, claims its slug."""

from fastapi import FastAPI

from app.health.router import router
from app.integration import Host


def register(app: FastAPI, host: Host) -> None:
    app.include_router(router)
    host.reserve("health")
