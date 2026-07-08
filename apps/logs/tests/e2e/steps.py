from datetime import UTC, datetime

from pytest_bdd import given, parsers, then, when


def _date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


# ── Seeding ──────────────────────────────────────────────────────────────────
@given(parsers.parse('an audit log entry "{event}" from org "{org}"'))
def step_seed_audit_org(driver, event, org):
    driver.seed_audit_from_org(event, org)


@given(parsers.parse('an audit log entry "{event}" from org "{org}" recorded on "{date}"'))
def step_seed_audit_org_dated(driver, event, org, date):
    driver.seed_audit_from_org(event, org, when=_date(date))


@given(parsers.parse('an audit log entry "{event}" attributed to "{email}"'))
def step_seed_audit_user(driver, event, email):
    driver.seed_audit_by_user(event, email)


# ── Filtering / sorting ──────────────────────────────────────────────────────
@when(parsers.parse('the admin filters the logs by org "{org}"'))
def step_filter_org(driver, org):
    driver.filter_logs_by_org(org)


@when(parsers.parse('the admin filters the logs by user "{email}"'))
def step_filter_user(driver, email):
    driver.filter_logs_by_user(email)


@when(parsers.parse('the admin filters the logs to dates from "{a}" to "{b}"'))
def step_filter_dates(driver, a, b):
    driver.filter_logs_by_dates(a, b)


@when(parsers.parse('the admin sorts the logs by "{column}" ascending'))
def step_sort_asc(driver, column):
    driver.sort_logs(column, "asc")


# ── Assertions ───────────────────────────────────────────────────────────────
@then(parsers.parse('the entry "{event}" is listed'))
def step_entry_listed(driver, event):
    driver.assert_entry_listed(event)


@then(parsers.parse('the entry "{event}" is not listed'))
def step_entry_not_listed(driver, event):
    driver.assert_entry_not_listed(event)


@then(parsers.parse('the entry "{event}" is listed with source "{source}"'))
def step_entry_source(driver, event, source):
    driver.assert_entry_source(event, source)


@then(parsers.parse('"{a}" is listed above "{b}"'))
def step_entry_above(driver, a, b):
    driver.assert_entry_above(a, b)


@then(
    parsers.parse(
        'the activity for "{date}" shows {audit:d} audit, {request:d} request, and {issue:d} issue'
    )
)
def step_activity(driver, date, audit, request, issue):
    driver.assert_activity(date, audit, request, issue)


# ── Access + empty state ─────────────────────────────────────────────────────
@when("the admin opens the logs screen")
def step_open_logs(driver):
    driver.open_logs_screen()


@then("the logs screen reports no entries")
def step_logs_empty(driver):
    driver.assert_logs_empty()


@when("they try to open the logs screen")
def step_try_open_logs(driver):
    driver.try_open_logs_screen()


@then("the logs screen is not found")
def step_logs_not_found(driver):
    driver.assert_logs_not_found()
