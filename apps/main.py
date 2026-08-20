"""The composition root: each context's ``mount()`` wires its routers, events and claimed slugs.

FastAPI matches routes in registration order, so registration follows each module's declared
``PHASE`` (:class:`apps.shared.integration.host.MountPhase`); ties keep the listing order below.
"""

from apps.api_keys.contract import integration as api_keys
from apps.auth.contract import integration as auth
from apps.calendar.contract import integration as calendar
from apps.console.contract import integration as console
from apps.files.contract import integration as files
from apps.health.contract import integration as health
from apps.issues.contract import integration as issues
from apps.learning.contract import integration as learning
from apps.metrics.contract import integration as metrics
from apps.organizations.contract import integration as organizations
from apps.pages.contract import integration as pages
from apps.profile.contract import integration as profile
from apps.public.contract import integration as public
from apps.shared.contract import integration as shared
from apps.shared.integration.host import host
from apps.shared.persistence.database import dispose_engines
from apps.timeline.contract import integration as timeline
from apps.todo.contract import integration as todo

_apps = sorted(
    (
        shared,
        auth,
        profile,
        health,
        issues,
        metrics,
        timeline,
        console,
        organizations,
        api_keys,
        files,
        todo,
        learning,
        pages,
        calendar,
        public,
    ),
    key=lambda module: module.PHASE,
)
for _app in _apps:
    _app.mount(host)

# Last hook registered, so last to run: Starlette fires shutdown handlers in registration order,
# and every context's own hook (task worker, event listener, metrics flusher, issue drain) still
# needs the pools while it stops.
host.on_shutdown(dispose_engines)

app = host.app
"""The ASGI entrypoint: hypercorn loads ``apps.main:app`` (see docker/docker-compose.yml)."""
