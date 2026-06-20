"""How the public context plugs into the running app: mounts the landing-page router."""

from fastapi import FastAPI

from app.integration import Host
from app.public.infra.router import router


def register(app: FastAPI, host: Host) -> None:
    app.include_router(router)
