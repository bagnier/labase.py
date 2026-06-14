from pytest_bdd import given, parsers, then, when


@when("they try to access the profile without signing in")
def step_access_profile_unauthenticated(driver):
    driver.visit_profile_unauthenticated()


@then("there is a link to their org dashboard")
def step_link_to_org_dashboard(driver):
    driver.assert_link_to_org_dashboard()


@when("they view the dashboard")
def step_view_dashboard(driver):
    driver.view_dashboard()


@then("there is a link to their todo list")
def step_link_to_todos(driver):
    driver.assert_link_to_todos()


@then("there is a link to the profile in the user footer")
def step_profile_link_in_footer(driver):
    driver.assert_profile_link_in_footer()


@then("there is no profile link in the navigation")
def step_no_profile_nav_link(driver):
    driver.assert_no_profile_nav_link()


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
