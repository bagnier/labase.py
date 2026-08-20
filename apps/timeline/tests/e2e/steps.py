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


@given(parsers.parse('a business event "{event}" about "{subject}" in org "{org}"'))
def step_seed_event_about(driver, event, subject, org):
    driver.seed_event_about(event, org, subject)


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


# Anchored regex, for the reason the request-log steps above are: the dated variant below adds a
# trailing clause, and parse's greedy fields would let this sentence swallow it whole.
_CORRELATED = (
    r'request "(?P<rid>[^"]+)" in org "(?P<org>[^"]+)" recorded a request log, '
    r'a business event "(?P<event>[^"]+)", and a captured error "(?P<error>[^"]+)"'
)


@given(parsers.re(_CORRELATED + "$"))
def step_seed_correlated(driver, rid, org, event, error):
    driver.seed_correlated_request(rid, org, event, error)


@given(parsers.re(_CORRELATED + r' on "(?P<date>[^"]+)"$'))
def step_seed_correlated_dated(driver, rid, org, event, error, date):
    driver.seed_correlated_request(rid, org, event, error, when=_date(date))


@given(parsers.parse('the timeline holds {count:d} business events in org "{org}"'))
def step_seed_many_events(driver, count, org):
    driver.seed_many_events(count, org)


@given(parsers.parse('the log level is "{level}"'))
def step_log_level_is(driver, level):
    driver.set_process_log_level(level)


@given(parsers.parse('a business event "{event}" is recorded in org "{org}"'))
def step_event_recorded(driver, event, org):
    driver.seed_event_from_org(event, org)


# ── Filtering / sorting ──────────────────────────────────────────────────────
@when(parsers.parse('the admin filters the timeline by org "{org}"'))
def step_filter_org(driver, org):
    driver.filter_timeline_by_org(org)


@when(parsers.parse('the admin filters the timeline by user "{email}"'))
def step_filter_user(driver, email):
    driver.filter_timeline_by_user(email)


@when(parsers.parse('the admin filters the timeline by source "{source}"'))
def step_filter_source(driver, source):
    driver.filter_timeline_by_source(source)


@when(parsers.parse('the admin filters the timeline by app "{app}"'))
def step_filter_app(driver, app):
    driver.filter_timeline_by_app(app)


@when(parsers.parse('the admin filters the timeline by level "{level}"'))
def step_filter_level(driver, level):
    driver.filter_timeline_by_level(level)


@when(parsers.parse('the admin filters the timeline by request "{rid}"'))
def step_filter_request(driver, rid):
    driver.filter_timeline_by_request(rid)


@when(parsers.parse('the admin searches the timeline for "{text}"'))
def step_search_text(driver, text):
    driver.search_timeline(text)


@when("the admin exports the filtered timeline as NDJSON")
def step_export_ndjson(driver):
    driver.export_timeline_ndjson()


@when("the admin exports the filtered timeline as CSV")
def step_export_csv(driver):
    driver.export_timeline_csv()


@when(parsers.parse('the admin filters the timeline to dates from "{a}" to "{b}"'))
def step_filter_dates(driver, a, b):
    driver.filter_timeline_by_dates(a, b)


@when(parsers.parse('the admin sorts the timeline by "{column}" ascending'))
def step_sort_asc(driver, column):
    driver.sort_timeline(column, "asc")


@when("the admin loads older entries")
def step_load_older(driver):
    driver.load_older_entries()


@when(parsers.parse('the admin views the activity by "{grain}"'))
def step_view_activity_grain(driver, grain):
    driver.view_activity_by(grain)


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


@then("the timeline offers to load older entries")
def step_offers_older(driver):
    driver.assert_offers_older_entries()


@then("the older entries continue the timeline without repeating it")
def step_older_do_not_repeat(driver):
    driver.assert_older_entries_do_not_repeat()


@then(parsers.parse('{n:d} logs entry from org "{org}" is listed'))
def step_request_count(driver, n, org):
    driver.assert_source_count("logs", n, org)


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
        'the activity for "{date}" shows {business:d} business, {logs:d} logs, and {issue:d} issue'
    )
)
def step_activity(driver, date, business, logs, issue):
    driver.assert_activity(date, business, logs, issue)


# ── Access + empty state ─────────────────────────────────────────────────────
@when("the admin opens the timeline")
def step_open_timeline(driver):
    driver.open_timeline()


@then("the timeline reports no entries")
def step_timeline_empty(driver):
    driver.assert_timeline_empty()


@when("they try to open the timeline")
def step_try_open_timeline(driver):
    driver.try_open_timeline()
