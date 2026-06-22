from pytest_bdd import given, parsers, then, when


@when("they try to access the console without signing in")
def step_access_console_unauthenticated(driver):
    driver.visit_console_unauthenticated()


@given(parsers.parse('a server admin is signed in as "{email}"'))
def step_admin_signed_in(driver, email):
    driver.sign_in_as_admin(email)


@when("they try to open the console")
def step_try_open_console(driver):
    driver.try_open_console()


@when("the admin opens the console")
def step_admin_opens_console(driver):
    driver.visit_console()


@then("the console is not found")
def step_console_not_found(driver):
    driver.assert_console_not_found()


@then(parsers.parse('the "{key}" overview is visible on the console'))
def step_console_overview_visible(driver, key):
    driver.assert_console_overview_visible(key)


@then(parsers.parse('the "{key}" console overview shows "{text}"'))
def step_console_overview_shows(driver, key, text):
    driver.assert_console_overview_shows(key, text)


@when(parsers.parse('the admin opens the settings for the "{app}" app'))
def step_open_settings(driver, app):
    driver.open_console_settings(app)


@when(parsers.parse('the admin sets the "{app}" setting "{key}" to "{value}"'))
def step_set_setting(driver, app, key, value):
    driver.set_console_setting(app, key, value)


@when(parsers.parse('they try to set the "{app}" setting "{key}" to "{value}"'))
def step_try_set_setting(driver, app, key, value):
    driver.try_set_console_setting(app, key, value)


@then(parsers.parse('the "{app}" setting "{key}" is shown as "{value}"'))
def step_setting_shown(driver, app, key, value):
    driver.assert_console_setting_shown(app, key, value)
