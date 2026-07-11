from pytest_bdd import given, parsers, then, when


@given(parsers.parse('a captured error "{title}" with {count:d} occurrences'))
def step_seed_captured_error(driver, title, count):
    driver.seed_captured_error(title, count)


@when(parsers.parse('another occurrence of "{title}" arrives from version "{version}"'))
def step_seed_more_occurrences(driver, title, version):
    driver.seed_captured_error(title, 1, version=version)


@when("the admin opens the issues screen")
def step_open_issues_screen(driver):
    driver.open_issues_screen()


@when(parsers.parse('the admin resolves the issue "{title}"'))
def step_resolve_issue(driver, title):
    driver.set_issue_status(title, "resolved")


@when(parsers.parse('the admin ignores the issue "{title}"'))
def step_ignore_issue(driver, title):
    driver.set_issue_status(title, "ignored")


@when(parsers.parse('the admin opens the issue "{title}"'))
def step_open_issue_detail(driver, title):
    driver.open_issue_detail(title)


@then(
    parsers.parse('the issue "{title}" is listed with status "{status}" and {count:d} occurrences')
)
def step_assert_issue_listed(driver, title, status, count):
    driver.assert_issue_listed(title, status, count)


@then(parsers.parse("the stack trace and {count:d} occurrences are shown"))
def step_assert_detail(driver, count):
    driver.assert_issue_detail_shows(count)


@when("they try to open the issues screen")
def step_try_open_issues_screen(driver):
    driver.try_open_issues_screen()
