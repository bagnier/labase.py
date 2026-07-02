"""Env/process diagnostics tile — folds into the "Settings" console tile via
``ConsoleOverview.group`` (see :mod:`apps.settings.infra.router`'s ``_fold_groups``).
"""

from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.domain import technical


async def overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    process = technical.process_snapshot()
    return ConsoleOverview(
        key="technical",
        title="Environment & process",
        icon="terminal-window",
        group="settings",
        data={"lines": [f"{len(technical.env_snapshot())} env vars", f"PID {process['pid']}"]},
    )
