"""How the auth context plugs into the running app: mounts the auth router, claims its slugs.

Event wiring for sign-up (``UserCreated`` emission, compensation) lives in the registration
orchestrator (:mod:`app.registration`), not here.
"""

from fastapi import FastAPI

from app.auth.infra.router import router
from app.integration import Host


def register(app: FastAPI, host: Host) -> None:
    app.include_router(router, prefix="/auth", tags=["auth"])
    host.reserve("auth", "login", "logout", "signup")
