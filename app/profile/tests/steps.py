from pytest_bdd import given, parsers, then, when


@given(parsers.parse('their display name is "{name}"'))
def step_have_display_name(driver, name):
    driver.update_display_name(name)


@when("they view their profile")
def step_view_profile(driver):
    driver.view_profile()


@when(parsers.parse('they update their display name to "{name}"'))
def step_update_display_name(driver, name):
    driver.update_display_name(name)


@when('they update their display name to ""')
def step_clear_display_name(driver):
    driver.update_display_name("")


@then(parsers.parse('their display name is "{name}"'))
def step_assert_display_name(driver, name):
    driver.assert_display_name(name)


@then(parsers.parse('their display name is still "{name}"'))
def step_assert_display_name_still(driver, name):
    driver.assert_display_name(name)


@then("the update is rejected")
def step_assert_update_rejected(driver):
    driver.assert_last_update_rejected()


@then("their email is shown as read-only")
def step_assert_email_read_only(driver):
    driver.assert_email_read_only()
