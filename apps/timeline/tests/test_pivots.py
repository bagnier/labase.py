"""Correlating by hand — the keys were on the row, and none of them was a link.

The timeline resolves every id to something readable and then leaves the reader to copy it into a
filter box: an issue row named the failure but not the issue, and org / user / request were text
where entity was already a link. The one filter that matters most on a bad day — *show me
everything about this request* — was the one requiring a copy-paste.
"""

import re
import uuid

from apps.shared.events.models import BusinessEventRecord
from apps.shared.tests.journal_seed import seed_fact

_ADMIN = "pivots@example.com"


def _timeline(driver, query: str = "") -> str:
    return driver.client().get(f"/console/timeline{query}", headers={"accept": "text/html"}).text


def test_an_issue_row_links_to_the_issue_it_is_an_occurrence_of(driver):
    """The row names the exception; the stack, the triage and the other occurrences are one
    click away and were reachable only by finding the issue again on its own screen."""
    driver.sign_in_as_admin(_ADMIN)
    driver.seed_error_from_org("ValueError: pivot boom", "Acme")

    body = _timeline(driver)

    assert re.search(r'href="/console/issues/[0-9a-f-]{36}"', body) is not None


def test_a_row_correlates_by_the_request_it_names(driver):
    """One request, three sources: the reason the request id is on every row at all."""
    driver.sign_in_as_admin(_ADMIN)
    request_id = uuid.uuid7()
    driver.run(
        seed_fact(BusinessEventRecord(app_name="todo", verb="created", request_id=request_id))
    )

    body = _timeline(driver)

    assert f'href="/console/timeline?request_id={request_id}"' in body


def test_a_row_correlates_by_the_org_it_names(driver):
    """Same for who and where — a resolved label an admin cannot act on is half a feature."""
    driver.sign_in_as_admin(_ADMIN)
    org_id = uuid.uuid7()
    driver.run(seed_fact(BusinessEventRecord(app_name="todo", verb="created", org_id=org_id)))

    body = _timeline(driver)

    assert f'href="/console/timeline?org_id={org_id}"' in body
