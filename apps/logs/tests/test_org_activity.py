"""The logs → org-dashboard contribution: aggregate counts shaped into a chart."""

import uuid
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from apps.logs.contract.integration import _ACTIVITY_DAYS, _org_overview
from apps.organizations.contract.overviews import OverviewQuery
from apps.shared.observability.audit import _insert_audit_log


def test_org_overview_spans_the_window_and_counts_the_orgs_own_events(driver):
    org_id = uuid.uuid4()
    other_org = uuid.uuid4()

    async def scenario():
        await _insert_audit_log("info", "todo.created", None, None, str(org_id), None, {})
        await _insert_audit_log("info", "todo.created", None, None, str(org_id), None, {})
        await _insert_audit_log("info", "todo.created", None, None, str(other_org), None, {})
        # The handler never touches the query session (it opens its own admin one).
        return await _org_overview(OverviewQuery(session=cast("AsyncSession", None), org_id=org_id))

    overview = driver.run(scenario())

    assert overview.key == "activity"
    assert overview.data["active"] is True
    config = overview.data["config"]
    assert len(config["options"]["xaxis"]["categories"]) == _ACTIVITY_DAYS
    audit_series = next(s for s in config["series"] if s["name"] == "Audit")
    assert audit_series["data"][-1] == 2  # today's bucket, this org only
