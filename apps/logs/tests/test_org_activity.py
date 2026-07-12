"""The logs → org-dashboard contribution: aggregate counts shaped into a chart."""

import uuid
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from apps.logs.contract.integration import _ACTIVITY_DAYS, _org_overview
from apps.organizations.contract.overviews import OverviewQuery
from apps.shared.observability.business_events import insert_business_event


def test_org_overview_spans_the_window_and_counts_the_orgs_own_events(driver):
    org_id = uuid.uuid4()
    other_org = uuid.uuid4()

    async def _seed(scoped_org: uuid.UUID) -> None:
        await insert_business_event(
            kind="todo.created",
            level="info",
            user_id=None,
            ip=None,
            org_id=str(scoped_org),
            request_id=None,
            payload=None,
        )

    async def scenario():
        await _seed(org_id)
        await _seed(org_id)
        await _seed(other_org)
        # The handler never touches the query session (it opens its own admin one).
        return await _org_overview(OverviewQuery(session=cast("AsyncSession", None), org_id=org_id))

    overview = driver.run(scenario())

    assert overview.key == "activity"
    assert overview.data["active"] is True
    config = overview.data["config"]
    assert len(config["options"]["xaxis"]["categories"]) == _ACTIVITY_DAYS
    event_series = next(s for s in config["series"] if s["name"] == "Events")
    assert event_series["data"][-1] == 2  # today's bucket, this org only
