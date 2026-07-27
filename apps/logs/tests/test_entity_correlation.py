"""Correlating the unified log by the concerned entity — every event of one todo/page/file."""

import uuid

from apps.shared.events.repository import insert_business_event

_ADMIN = "entity-corr@example.com"


def _seed(app_name: str, verb: str, entity_id: uuid.UUID):
    return insert_business_event(
        app_name=app_name,
        verb=verb,
        user_id=None,
        ip=None,
        org_id=None,
        entity_id=entity_id,
        request_id=None,
        payload=None,
    )


def test_logs_filter_by_entity_keeps_only_that_entitys_events(driver):
    driver.sign_in_as_admin(_ADMIN)
    todo, other = uuid.uuid7(), uuid.uuid7()  # entity_id is a uuid pk (weak, table-agnostic FK)
    driver.run(_seed("todo", "created", todo))
    driver.run(_seed("todo", "ticked", todo))
    driver.run(_seed("calendar", "event_created", other))

    body = (
        driver.client().get(f"/console/logs?entity_id={todo}", headers={"accept": "text/html"}).text
    )

    assert "todo.created" in body  # the concerned entity's events…
    assert "todo.ticked" in body
    assert "calendar.event_created" not in body  # …and nothing from another entity
    # The firehose/issue sources carry no entity, so an entity filter excludes them wholesale.
    assert "request.finished" not in body
