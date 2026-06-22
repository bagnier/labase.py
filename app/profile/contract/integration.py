"""How the profile context plugs into the running app: mounts its router, claims its slug."""

from fastapi import FastAPI

from app.profile.contract.queries import profile_handle_taken
from app.profile.infra.router import router
from app.shared.host import Host
from app.shared.slug_registry import register_open_list


def mount(app: FastAPI, host: Host) -> None:
    app.include_router(router, tags=["profile"])
    host.reserve("profile")
    register_open_list("profiles", profile_handle_taken)
