"""How the console context plugs into the running app: mounts the admin router, claims slugs."""

from fastapi import FastAPI

from app.console.infra.router import router
from app.shared.host import Host


def register(app: FastAPI, host: Host) -> None:
    app.include_router(router, prefix="/console")
    host.reserve("console", "admin")
