from fastapi import FastAPI

from apps.auth.contract import integration as auth
from apps.files.contract import integration as files
from apps.health.contract import integration as health
from apps.learning.contract import integration as learning
from apps.organizations.contract import integration as organizations
from apps.profile.contract import integration as profile
from apps.public.contract import integration as public
from apps.settings.contract import integration as console
from apps.shared.contract import integration as shared
from apps.shared.host import host
from apps.todo.contract import integration as todo

app = FastAPI(title="labase")

# Composition root: each context's mount() wires its routers, events, and claimed slugs.
# Order matters: contexts mounting under the `/{org_handle}/...` catch-all (organizations,
# files, todo, learning) must come last, so fixed-prefix routers like /console/{app} are never
# shadowed by it. Keep them at the tail of this tuple.
_apps = (shared, auth, profile, public, health, console, organizations, files, todo, learning)
for _app in _apps:
    _app.mount(app, host)
