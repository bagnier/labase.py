"""The Timeline shows and searches a fact's pinned ``entity_name``."""

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
    driver.sign_in_as_admin(_ADMIN)
    driver.run(_seed("created", _TITLE))

    body = _timeline(driver)

    assert _TITLE in body


def test_free_text_finds_a_fact_by_the_name_of_its_entity(driver):
    driver.sign_in_as_admin(_ADMIN)
    driver.run(_seed("created", _TITLE))
    driver.run(_seed("deleted", _OTHER))

    body = _timeline(driver, "?q=oat")

    assert (_TITLE in body, _OTHER in body) == (True, False)
