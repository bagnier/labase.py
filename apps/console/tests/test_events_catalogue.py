"""The console's event catalogue — the per-app Events panel and the global reaction graph.

Both read straight from the event wiring (populated at mount), so the assertions are on the
real wiring the app declares, not a fixture.
"""


def test_events_screen_shows_the_event_to_reaction_graph(driver):
    driver.sign_in_as_admin("events-admin@example.com")
    body = driver.client().get("/console/events", headers={"accept": "text/html"}).text
    assert "data-event-graph" in body
    # UserCreated fans out to two durable reactions — the org seeder and the first-admin bootstrap.
    assert "auth.user_created" in body
    assert "create_personal_org" in body
    assert "bootstrap_first_admin" in body


def test_events_screen_is_reachable_as_json(driver):
    driver.sign_in_as_admin("events-admin-json@example.com")
    payload = driver.client().get("/console/events", headers={"accept": "application/json"}).json()
    kinds = {row["kind"] for row in payload["events"]}
    assert "auth.user_deleted" in kinds  # has the forget-user reactions
    deleted = next(row for row in payload["events"] if row["kind"] == "auth.user_deleted")
    reactions = {r["name"] for r in deleted["reactions"]}
    assert {"organizations_forget", "profile_forget"} <= reactions


def test_app_page_shows_its_emitted_and_listened_events(driver):
    driver.sign_in_as_admin("events-admin-app@example.com")
    body = driver.client().get("/console/todo", headers={"accept": "text/html"}).text
    assert "data-events-panel" in body
    assert "todo.created" in body  # an emitted event
    assert "todo_welcome" in body  # todo reacts to organizations.created


def test_events_screen_json_groups_all_declared_events_by_app(driver):
    driver.sign_in_as_admin("events-admin-by-app-json@example.com")
    payload = driver.client().get("/console/events", headers={"accept": "application/json"}).json()
    issues_row = next(row for row in payload["by_app"] if row["app"] == "issues")
    # issues declares three events; only two (opened, regressed) have a durable reaction.
    assert issues_row == {
        "app": "issues",
        "kinds": ["issues.opened", "issues.regressed", "issues.status_changed"],
    }


def test_events_screen_all_events_tab_lists_declared_events_with_no_reaction(driver):
    driver.sign_in_as_admin("events-admin-by-app-html@example.com")
    body = driver.client().get("/console/events", headers={"accept": "text/html"}).text
    assert 'data-tab="all"' in body
    assert 'data-tab="connected"' in body
    # issues.status_changed has no durable reaction, so it never appears in the connected graph —
    # its presence here proves the "All events" tab reads the full catalogue, not the graph.
    assert "issues.status_changed" in body
