from fastapi import FastAPI

from app.auth.contract import integration as auth
from app.console.contract import integration as console
from app.files.contract import integration as files
from app.health.contract import integration as health
from app.learning.contract import integration as learning
from app.organizations.contract import integration as organizations
from app.profile.contract import integration as profile
from app.public.contract import integration as public
from app.shared.contract import integration as shared
from app.shared.host import host
from app.todo.contract import integration as todo

app = FastAPI(title="labase")

# Composition root: each context's mount() wires its routers, events, and claimed slugs.
# Contexts that mount under the `/{org_handle}/...` catch-all (MOUNTS_UNDER_ORG_HANDLE) are
# mounted last, so fixed-prefix routers like /console/{app} are never shadowed by it.
_apps = (shared, auth, profile, public, health, console, organizations, files, todo, learning)
for _app in sorted(_apps, key=lambda c: getattr(c, "MOUNTS_UNDER_ORG_HANDLE", False)):
    _app.mount(app, host)
