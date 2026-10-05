"""The Timeline shows a fact's pinned actor and org names, not a live lookup that finds
nothing once the account or org is gone."""

import uuid

from apps.shared.events.models import BusinessEventRecord
from apps.shared.tests.journal_seed import seed_fact

_ADMIN = "actor-naming@example.com"
_ACTOR_EMAIL = "alice@example.com"
_ORG_NAME = "Acme Widgets"


def _seed_fact_from_a_gone_actor_and_org():
    """A fact whose ids resolve nowhere, as after a closed account or deleted org. A made-up
    ``app_name`` keeps it off the demo-naming ratchet (tests/meta/test_surfaces.py)."""
    return seed_fact(
        BusinessEventRecord(
            app_name="sample",
            verb="created",
            user_id=uuid.uuid7(),
            user_name=_ACTOR_EMAIL,
            org_id=uuid.uuid7(),
            org_name=_ORG_NAME,
        )
    )


def test_a_row_shows_the_actor_and_org_names_the_fact_pinned(driver):
    driver.sign_in_as_admin(_ADMIN)
    driver.run(_seed_fact_from_a_gone_actor_and_org())

    body = driver.client().get("/console/timeline", headers={"accept": "text/html"}).text

    assert (_ACTOR_EMAIL in body, _ORG_NAME in body) == (True, True)


def test_the_csv_export_carries_the_pinned_names_too(driver):
    driver.sign_in_as_admin(_ADMIN)
    driver.run(_seed_fact_from_a_gone_actor_and_org())

    body = driver.client().get("/console/timeline/export?format=csv").text

    assert (_ACTOR_EMAIL in body, _ORG_NAME in body) == (True, True)
