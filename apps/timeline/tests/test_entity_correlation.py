"""Filtering the Timeline by entity: every fact of one todo, page or file."""

import uuid

from apps.shared.events.models import BusinessEventRecord
from apps.shared.tests.journal_seed import seed_fact

_ADMIN = "entity-corr@example.com"


def _seed(app_name: str, verb: str, entity_id: uuid.UUID):
    return seed_fact(BusinessEventRecord(app_name=app_name, verb=verb, entity_id=entity_id))


def test_timeline_filter_by_entity_keeps_only_that_entitys_events(driver):
    driver.sign_in_as_admin(_ADMIN)
    todo, other = uuid.uuid7(), uuid.uuid7()
    driver.run(_seed("todo", "created", todo))
    driver.run(_seed("todo", "ticked", todo))
    driver.run(_seed("calendar", "event_created", other))

    body = (
        driver.client()
        .get(f"/console/timeline?entity_id={todo}", headers={"accept": "text/html"})
        .text
    )

    assert "todo.created" in body
    assert "todo.ticked" in body
    assert "calendar.event_created" not in body
    assert "request.finished" not in body
