"""Correlating the unified log by the concerned entity — every event of one todo/page/file."""

from apps.shared.events.repository import insert_business_event

_ADMIN = "entity-corr@example.com"


def _seed(kind: str, entity_id: str):
    return insert_business_event(
        kind=kind,
        level="info",
        user_id=None,
        ip=None,
        org_id=None,
        entity_id=entity_id,
        request_id=None,
        payload=None,
    )


def test_logs_filter_by_entity_keeps_only_that_entitys_events(driver):
    driver.sign_in_as_admin(_ADMIN)
    driver.run(_seed("todo.created", "todo-1"))
    driver.run(_seed("todo.ticked", "todo-1"))
    driver.run(_seed("calendar.event_created", "cal-9"))

    body = (
        driver.client().get("/console/logs?entity_id=todo-1", headers={"accept": "text/html"}).text
    )

    assert "todo.created" in body  # the concerned entity's events…
    assert "todo.ticked" in body
    assert "calendar.event_created" not in body  # …and nothing from another entity
    # The firehose/issue sources carry no entity, so an entity filter excludes them wholesale.
    assert "request.finished" not in body
