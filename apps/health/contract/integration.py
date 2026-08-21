"""How the health context plugs into the running app: mounts the probe router, claims its slug.

The probes are the one surface with nothing to configure and nothing server-wide to count, which
is exactly why the console tile matters: without it an admin has no way to learn, from the console,
that the probes exist or what an orchestrator should poll. The tile carries no aggregate — it names
the two paths and the readiness of the instance that answered, and links to the probe itself.
"""

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.health.router import readiness_failures, router
from apps.shared.integration.host import Host, MountPhase

PHASE = MountPhase.FOUNDATION


def mount(host: Host) -> None:
    host.app.include_router(router)
    host.reserve("health")
    host.contribs.provide(ConsoleOverviewQuery, _console_overview)


async def _console_overview(_query: ConsoleOverviewQuery) -> ConsoleOverview:
    """No database read: the probe's verdict is process state, and the query's session reaching
    this code already answers the only question `/health/ready` asks."""
    failures = readiness_failures()
    state = "ready" if not failures else f"degraded — {failures} failed probes"
    return ConsoleOverview(
        key="health",
        title="Health",
        icon="heartbeat",
        section="operations",
        href="/health/ready",
        data={"lines": ["/health/live — liveness", "/health/ready — readiness", state]},
    )
