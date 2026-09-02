"""How the tasks context plugs into the running app.

``apps/tasks`` is the *read* side of the durable queue: the screen that says what work the async
substrate still owes and what it ran. The queue itself — the table, the worker, the retry and park
— stays in ``apps/shared/queue``, a foundation every app enqueues onto. This app never writes to
it; it only reads what the substrate and the log sink already recorded.

NOTE: mounted BEFORE the console context so its /console/tasks route registers ahead of the
console's /console/{app} catch-all.
"""

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
    """Console tile → the async substrate's backlog. Parked first, because that is the number that
    means work nobody will redo: an issue was opened for the *bug*, and the row is still owed."""
    counts = await count_unfinished_tasks(query.session)
    # Every state that has rows, worst first — "nothing owed" is a claim about the whole queue,
    # and a healthy server still holds the recurring singletons, which are owed like anything else.
    lines = [f"{counts[state]} {state}" for state in TASK_STATES if counts[state]]
    return ConsoleOverview(
        key=TASKS_APP,
        title="Tasks",
        icon="stack",
        section="operations",
        href="/console/tasks",
        data={"lines": lines or ["Nothing owed"]},
    )
