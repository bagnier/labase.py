from pytest_bdd import given, parsers, then, when


# ── given: existing events ───────────────────────────────────────────────────---
@given(parsers.parse('an event "{title}" from "{start}" to "{end}"'))
@given(parsers.parse('a past event "{title}" from "{start}" to "{end}"'))
def step_given_event(driver, title, start, end):
    driver.given_event(title, start, end)


# ── when: browse ─────────────────────────────────────────────────────────────--
@when("they view the calendar")
def step_view_calendar(driver):
    driver.view_calendar()


@when(parsers.parse('"{email}" views the calendar'))
def step_view_calendar_as(driver, email):
    driver.view_calendar_as(email)


# ── when: create ─────────────────────────────────────────────────────────────--
@when(parsers.parse('they create an event "{title}" from "{start}" to "{end}"'))
def step_create_event(driver, title, start, end):
    driver.create_event(title, start, end)


@when(
    parsers.parse(
        'they create an event "{title}" from "{start}" to "{end}"'
        ' at "{location}" described as "{description}"'
    )
)
def step_create_event_full(driver, title, start, end, location, description):
    driver.create_event_full(title, start, end, location, description)


@when(parsers.parse('they try to create an event with no title from "{start}" to "{end}"'))
def step_try_create_no_title(driver, start, end):
    driver.try_create_event(None, start, end)


@when(parsers.parse('they try to create an event "{title}" from "{start}" to "{end}"'))
def step_try_create_event(driver, title, start, end):
    driver.try_create_event(title, start, end)


# ── when: view / edit / delete ───────────────────────────────────────────────--
@when(parsers.parse('they open the event "{title}"'))
def step_open_event(driver, title):
    driver.open_event(title)


@when(parsers.parse('they rename the event "{title}" to "{new_title}"'))
def step_rename_event(driver, title, new_title):
    driver.rename_event(title, new_title)


@when(parsers.parse('they reschedule the event "{title}" to start "{start}" and end "{end}"'))
def step_reschedule_event(driver, title, start, end):
    driver.reschedule_event(title, start, end)


@when(parsers.parse('they delete the event "{title}"'))
def step_delete_event(driver, title):
    driver.delete_event(title)


# ── then ─────────────────────────────────────────────────────────────────────--
@then("no events appear in the calendar")
def step_no_events(driver):
    driver.assert_no_events()


@then(parsers.parse("the events appear in order: {titles}"))
def step_event_order(driver, titles):
    items = [t.strip().strip('"') for t in titles.split(",")]
    driver.assert_event_order(items)


@then(parsers.parse('"{title}" appears in the calendar'))
def step_event_visible(driver, title):
    driver.assert_event_visible(title)


@then(parsers.parse('"{title}" does not appear in the calendar'))
@then(parsers.parse('"{title}" no longer appears in the calendar'))
def step_event_absent(driver, title):
    driver.assert_event_absent(title)


@then(parsers.parse('the event shows the location "{location}"'))
def step_event_location(driver, location):
    driver.assert_event_location(location)


@then(parsers.parse('the event shows the description "{description}"'))
def step_event_description(driver, description):
    driver.assert_event_description(description)


@then("the event is rejected")
def step_event_rejected(driver):
    driver.assert_event_rejected()


@then(parsers.parse('the event shows the time "{when}"'))
def step_event_when(driver, when):
    driver.assert_event_when(when)


@then(parsers.parse('the event "{title}" shows the time "{when}"'))
def step_named_event_when(driver, title, when):
    driver.assert_named_event_when(title, when)
