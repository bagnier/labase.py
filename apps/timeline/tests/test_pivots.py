"""Each key on a Timeline row is a link: to the issue, or to the filter on that key."""

import re
import uuid

from apps.shared.events.models import BusinessEventRecord
from apps.shared.tests.journal_seed import seed_fact

_ADMIN = "pivots@example.com"


def _timeline(driver, query: str = "") -> str:
    return driver.client().get(f"/console/timeline{query}", headers={"accept": "text/html"}).text


def test_an_issue_row_links_to_the_issue_it_is_an_occurrence_of(driver):
    driver.sign_in_as_admin(_ADMIN)
    driver.seed_error_from_org("ValueError: pivot boom", "Acme")

    body = _timeline(driver)

    assert re.search(r'href="/console/issues/[0-9a-f-]{36}"', body) is not None


def test_a_row_correlates_by_the_request_it_names(driver):
    driver.sign_in_as_admin(_ADMIN)
    request_id = uuid.uuid7()
    driver.run(
        seed_fact(BusinessEventRecord(app_name="todo", verb="created", request_id=request_id))
    )

    body = _timeline(driver)

    assert f'href="/console/timeline?request_id={request_id}"' in body


def test_a_row_correlates_by_the_org_it_names(driver):
    driver.sign_in_as_admin(_ADMIN)
    org_id = uuid.uuid7()
    driver.run(seed_fact(BusinessEventRecord(app_name="todo", verb="created", org_id=org_id)))

    body = _timeline(driver)

    assert f'href="/console/timeline?org_id={org_id}"' in body
