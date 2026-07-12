"""The console "Business events" screen — every app's typed events, grouped per app."""

from apps.shared.observability.business_events import insert_business_event

_ADMIN = "events-screen@example.com"


def _seed(kind: str):
    return insert_business_event(
        kind=kind,
        level="info",
        user_id=None,
        ip=None,
        org_id=None,
        request_id=None,
        payload=None,
    )


def test_console_events_screen_groups_events_by_app(driver):
    driver.sign_in_as_admin(_ADMIN)
    driver.run(_seed("todo.created"))
    driver.run(_seed("calendar.event_created"))

    body = driver.client().get("/console/events", headers={"accept": "text/html"}).text

    assert 'data-app="todo"' in body  # one section per app
    assert 'data-app="calendar"' in body
    assert "Created" in body  # todo.created, humanised
    assert "Event created" in body  # calendar.event_created, humanised
    assert "todo.created" not in body  # the raw kind never leaks to the page


def test_console_events_screen_focuses_a_single_app(driver):
    driver.sign_in_as_admin(_ADMIN)
    driver.run(_seed("todo.created"))
    driver.run(_seed("calendar.event_created"))

    body = driver.client().get("/console/events?app=todo", headers={"accept": "text/html"}).text

    assert 'data-app="todo"' in body
    assert 'data-app="calendar"' not in body  # the focus chip scopes to one app
