"""The health mount. Its console tile names the probe paths and the answering instance's
readiness, so an admin learns what an orchestrator should poll.
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
    """No database read: the verdict is process state."""
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
