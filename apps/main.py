"""The composition root: mounts every context in ``PHASE`` order (see
:class:`apps.shared.integration.host.MountPhase`), ties in the listing order below.
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
from apps.tasks.contract import integration as tasks
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
        tasks,
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

# Registered last, so it runs last: the other shutdown hooks still need the pools.
host.on_shutdown(dispose_engines)

app = host.app
"""The ASGI entrypoint: hypercorn loads ``apps.main:app`` (see docker/docker-compose.yml)."""
