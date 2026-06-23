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
# Each app reads its own settings inside mount() (console.get_app_settings); toggleable apps
# gate their wiring on the resulting `.enabled`.
# Order matters: contexts mounting under the `/{org_handle}/...` catch-all (organizations,
# files, todo, learning) must come last, so fixed-prefix routers like /console/{app} are never
# shadowed by it. Keep them at the tail of this tuple.
_apps = (shared, auth, profile, public, health, console, organizations, files, todo, learning)
for _app in _apps:
    _app.mount(app, host)
