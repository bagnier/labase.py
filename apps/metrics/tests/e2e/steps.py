from pytest_bdd import given, parsers, then, when


@given(
    parsers.parse(
        'recorded traffic of {requests:d} requests on "{label}" '
        "with {errors:d} errors at around {ms:d} ms"
    )
)
def step_seed_traffic(driver, requests, label, errors, ms):
    driver.seed_traffic(label, requests, errors, ms)


@when("the admin opens the load screen")
def step_open_load_screen(driver):
    driver.open_load_screen()


@then(
    parsers.parse(
        'the route "{label}" is listed with {requests:d} requests and a {rate:d}% error rate'
    )
)
def step_assert_route_listed(driver, label, requests, rate):
    driver.assert_route_load(label, requests, rate)


@then(parsers.parse('the route "{label}" shows a p95 of {p95:d} ms'))
def step_assert_route_p95(driver, label, p95):
    driver.assert_route_p95(label, p95)


@then(parsers.parse('the route "{label}" shows an average of {avg:d} ms'))
def step_assert_route_avg(driver, label, avg):
    driver.assert_route_avg(label, avg)


@then("the load screen reports no recorded traffic")
def step_assert_load_empty(driver):
    driver.assert_load_screen_empty()


@when("the admin fetches the metrics exposition")
def step_fetch_exposition(driver):
    driver.fetch_metrics_exposition()


@then("the exposition reports requests on the console route")
def step_assert_exposition(driver):
    driver.assert_exposition_reports_console_route()


@when("they try to open the load screen")
def step_try_open_load_screen(driver):
    driver.try_open_load_screen()


@when("they try to fetch the metrics exposition")
def step_try_fetch_exposition(driver):
    driver.try_fetch_metrics_exposition()
