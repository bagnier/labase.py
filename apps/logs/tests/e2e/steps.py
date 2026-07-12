from datetime import UTC, datetime

from pytest_bdd import given, parsers, then, when


def _date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


# ── Seeding ──────────────────────────────────────────────────────────────────
@given(parsers.parse('a business event "{event}" from org "{org}"'))
def step_seed_event_org(driver, event, org):
    driver.seed_event_from_org(event, org)


@given(parsers.parse('a business event "{event}" from org "{org}" recorded on "{date}"'))
def step_seed_event_org_dated(driver, event, org, date):
    driver.seed_event_from_org(event, org, when=_date(date))


@given(parsers.parse('a business event "{event}" attributed to "{email}"'))
def step_seed_event_user(driver, event, email):
    driver.seed_event_by_user(event, email)


# Anchored regex (not parse): the "at level" variants below share this prefix, and parse's
# fields greedily swallow the inner quotes — the `[^"]+` + `$` keeps each sentence unambiguous.
@given(parsers.re(r'a request log entry "(?P<event>[^"]+)" from org "(?P<org>[^"]+)"$'))
def step_seed_request_org(driver, event, org):
    driver.seed_request_from_org(event, org)


@given(parsers.parse('a request log entry "{event}" from org "{org}" recorded on "{date}"'))
def step_seed_request_org_dated(driver, event, org, date):
    driver.seed_request_from_org(event, org, when=_date(date))


@given(parsers.parse('a request log entry "{event}" at level "{level}" from org "{org}"'))
def step_seed_request_leveled(driver, event, level, org):
    driver.seed_request_from_org(event, org, level=level)


@given(parsers.re(r'an error log entry "(?P<event>[^"]+)" from org "(?P<org>[^"]+)"$'))
def step_seed_error_org(driver, event, org):
    driver.seed_error_from_org(event, org)


@given(parsers.parse('an error log entry "{event}" from org "{org}" recorded on "{date}"'))
def step_seed_error_org_dated(driver, event, org, date):
    driver.seed_error_from_org(event, org, when=_date(date))


@given(parsers.parse('an error log entry "{event}" at level "{level}" from org "{org}"'))
def step_seed_error_leveled(driver, event, level, org):
    driver.seed_error_from_org(event, org)


@given(
    parsers.parse(
        'request "{rid}" in org "{org}" recorded a request log, '
        'a business event "{event}", and a captured error "{error}"'
    )
)
def step_seed_correlated(driver, rid, org, event, error):
    driver.seed_correlated_request(rid, org, event, error)


@given(parsers.parse('the log level is "{level}"'))
def step_log_level_is(driver, level):
    driver.set_process_log_level(level)


@given(parsers.parse('a business event "{event}" is recorded in org "{org}"'))
def step_event_recorded(driver, event, org):
    driver.seed_event_from_org(event, org)


# ── Filtering / sorting ──────────────────────────────────────────────────────
@when(parsers.parse('the admin filters the logs by org "{org}"'))
def step_filter_org(driver, org):
    driver.filter_logs_by_org(org)


@when(parsers.parse('the admin filters the logs by user "{email}"'))
def step_filter_user(driver, email):
    driver.filter_logs_by_user(email)


@when(parsers.parse('the admin filters the logs by source "{source}"'))
def step_filter_source(driver, source):
    driver.filter_logs_by_source(source)


@when(parsers.parse('the admin filters the logs by app "{app}"'))
def step_filter_app(driver, app):
    driver.filter_logs_by_app(app)


@when(parsers.parse('the admin filters the logs by level "{level}"'))
def step_filter_level(driver, level):
    driver.filter_logs_by_level(level)


@when(parsers.parse('the admin filters the logs by request "{rid}"'))
def step_filter_request(driver, rid):
    driver.filter_logs_by_request(rid)


@when(parsers.parse('the admin searches the logs for "{text}"'))
def step_search_text(driver, text):
    driver.search_logs(text)


@when("the admin exports the filtered logs as NDJSON")
def step_export_ndjson(driver):
    driver.export_logs_ndjson()


@when("the admin exports the filtered logs as CSV")
def step_export_csv(driver):
    driver.export_logs_csv()


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
        'the request entry, the business event "{event}", and the error "{error}" are all listed'
    )
)
def step_correlated_all_listed(driver, event, error):
    driver.assert_all_listed("request.finished", event, error)


@then(parsers.parse("{n:d} request entry is listed"))
def step_request_count(driver, n):
    driver.assert_source_count("request", n)


@then(parsers.parse('the export contains "{needle}"'))
def step_export_contains(driver, needle):
    driver.assert_export_contains(needle)


@then(parsers.parse('the export does not contain "{needle}"'))
def step_export_excludes(driver, needle):
    driver.assert_export_excludes(needle)


@then(parsers.parse('the CSV export has a header row and lists "{needle}"'))
def step_csv_export(driver, needle):
    driver.assert_csv_export(needle)


@then(
    parsers.parse(
        'the activity for "{date}" shows {event:d} event, {request:d} request, and {issue:d} issue'
    )
)
def step_activity(driver, date, event, request, issue):
    driver.assert_activity(date, event, request, issue)


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
