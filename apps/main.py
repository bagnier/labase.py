from apps.api_keys.contract import integration as api_keys
from apps.auth.contract import integration as auth
from apps.calendar.contract import integration as calendar
from apps.files.contract import integration as files
from apps.health.contract import integration as health
from apps.issues.contract import integration as issues
from apps.learning.contract import integration as learning
from apps.organizations.contract import integration as organizations
from apps.pages.contract import integration as pages
from apps.profile.contract import integration as profile
from apps.public.contract import integration as public
from apps.settings.contract import integration as console
from apps.shared.contract import integration as shared
from apps.shared.host import host
from apps.todo.contract import integration as todo

# Composition root: each context's mount() wires its routers, events, and claimed slugs.
# Order matters: FastAPI matches routes in registration order, not by specificity.
# - public mounts GET /{slug} (single-segment catch-all) and must come LAST so fixed-prefix
#   routers like /console and /organizations are never shadowed by it.
# - org-scoped contexts (organizations, files, todo, learning, pages) mount /{org_handle}/...
#   catch-alls and must also come after fixed-prefix routers for the same reason.
_apps = (
    shared,
    auth,
    profile,
    health,
    issues,  # before console: its /console/issues routes must precede /console/{app}
    console,
    organizations,
    api_keys,
    files,
    todo,
    learning,
    pages,
    calendar,
    public,
)
for _app in _apps:
    _app.mount(host)

# ASGI entrypoint: hypercorn loads ``apps.main:app`` (see docker/docker-compose.yml).
app = host.app
