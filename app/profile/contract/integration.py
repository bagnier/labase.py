"""How the profile context plugs into the running app: mounts its router, claims its slug."""

from fastapi import FastAPI

from app.profile.infra.router import router
from app.shared.host import Host


def register(app: FastAPI, host: Host) -> None:
    app.include_router(router, tags=["profile"])
    host.reserve("profile")
