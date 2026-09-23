"""What a fact says about who did it and where — the half only a business event can pin.

``emit`` resolves the actor's handle and the org's name *at write time* and pins them on the
fact's own ``user_name``/``org_name`` columns, so the journal stays legible once an account is
closed or an org renamed. The timeline read them live instead of off the fact: an id with no
``profiles`` row or ``organizations`` row left resolves to nothing, and the row fell back to
eight hex characters where the fact still held the name.
"""

import uuid

from apps.shared.events.models import BusinessEventRecord
from apps.shared.tests.journal_seed import seed_fact

_ADMIN = "actor-naming@example.com"
_ACTOR_EMAIL = "alice@example.com"
_ORG_NAME = "Acme Widgets"


def _seed_fact_from_a_gone_actor_and_org():
    """A fact whose ``user_id``/``org_id`` resolve nowhere (no signed-up account, no org row) —
    standing in for the account closed, and the org renamed or deleted, since the write path
    itself resolves names live at the moment the fact is recorded."""
    return seed_fact(
        BusinessEventRecord(
            app_name="todo",
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
