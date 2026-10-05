"""The tasks mount: the read side of ``apps/shared/queue``, which it never writes."""

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.shared.integration.host import Host, MountPhase
from apps.shared.queue import TASK_STATES, count_unfinished_tasks
from apps.tasks.infra.router import router

PHASE = MountPhase.CONSOLE_SCREEN

TASKS_APP = "tasks"


def mount(host: Host) -> None:
    host.contribs.provide(ConsoleOverviewQuery, _overview)
    host.app.include_router(router, prefix="/console/tasks")


async def _overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    """The console tile: rows owed per state, parked first, as nobody will redo them."""
    counts = await count_unfinished_tasks(query.session)
    # Recurring rows count too: a healthy server always owes them.
    lines = [f"{counts[state]} {state}" for state in TASK_STATES if counts[state]]
    return ConsoleOverview(
        key=TASKS_APP,
        title="Tasks",
        icon="stack",
        section="operations",
        href="/console/tasks",
        data={"lines": lines or ["Nothing owed"]},
    )
