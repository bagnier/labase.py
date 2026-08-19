"""What a fact says about the entity it concerns — the half that was written and never read.

``emit`` resolves the subject's readable name and pins it on its own ``entity_name`` column, so
the journal stays legible after a rename or a deletion. The timeline then showed neither: its
entry type had no such field, and the free-text filter searched ``kind`` and the residual
``payload`` — out of which ``entity_name`` had just been lifted. So the column an admin most wants
to search on was the one column the search could not see, and the Entity cell was a truncated uuid.
"""

import uuid

from apps.shared.events.models import BusinessEventRecord
from apps.shared.tests.journal_seed import seed_fact

_ADMIN = "entity-naming@example.com"
_TITLE = "Buy oat milk"
_OTHER = "Renew the domain"


def _seed(verb: str, entity_name: str):
    return seed_fact(
        BusinessEventRecord(
            app_name="todo", verb=verb, entity_id=uuid.uuid7(), entity_name=entity_name
        )
    )


def _timeline(driver, query: str = "") -> str:
    return driver.client().get(f"/console/timeline{query}", headers={"accept": "text/html"}).text


def test_a_fact_names_the_entity_it_concerns(driver):
    """A row reading ``todo.created`` beside twelve hex characters says which *kind* of thing
    happened and nothing about which one — while the journal knew all along."""
    driver.sign_in_as_admin(_ADMIN)
    driver.run(_seed("created", _TITLE))

    body = _timeline(driver)

    assert _TITLE in body


def test_free_text_finds_a_fact_by_the_name_of_its_entity(driver):
    """The search an admin actually types: not the dotted kind, which they would have to know,
    but the name of the thing — the title of the todo, the handle of the org."""
    driver.sign_in_as_admin(_ADMIN)
    driver.run(_seed("created", _TITLE))
    driver.run(_seed("deleted", _OTHER))

    body = _timeline(driver, "?q=oat")

    assert (_TITLE in body, _OTHER in body) == (True, False)
