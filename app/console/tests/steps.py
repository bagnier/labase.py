from pytest_bdd import when


@when("they try to access the console without signing in")
def step_access_console_unauthenticated(driver):
    driver.visit_console_unauthenticated()
