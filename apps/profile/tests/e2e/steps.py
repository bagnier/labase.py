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


@given(parsers.parse('their handle is "{name}"'))
def step_have_handle(driver, name):
    driver.update_handle(name)


@when("they view their profile")
def step_view_profile(driver):
    driver.view_profile()


@when(parsers.parse('they update their handle to "{name}"'))
def step_update_handle(driver, name):
    driver.update_handle(name)


@when('they update their handle to ""')
def step_clear_handle(driver):
    driver.update_handle("")


@then(parsers.parse('their handle is "{name}"'))
def step_assert_handle(driver, name):
    driver.assert_handle(name)


@then("the update is rejected")
def step_assert_update_rejected(driver):
    driver.assert_last_update_rejected()


@then("their email is shown as read-only")
def step_assert_email_read_only(driver):
    driver.assert_email_read_only()


@when(parsers.parse('they request to change their email to "{new_email}" using password "{pw}"'))
def step_request_email_change(driver, new_email, pw):
    driver.request_email_change(new_email, pw)


@then("they are told a confirmation email is on its way")
def step_assert_email_change_pending(driver):
    driver.assert_email_change_pending()


@then(parsers.parse('an email change link is delivered to "{email}"'))
def step_assert_email_change_delivered(driver, email):
    driver.assert_email_change_delivered(email)


@when(parsers.parse('they confirm the change using the link emailed to "{email}"'))
def step_confirm_email_change(driver, email):
    driver.confirm_email_change(email)


@then("the email change is rejected")
def step_assert_email_change_rejected(driver):
    driver.assert_email_change_rejected()


@then("the email change option is not offered")
def step_assert_email_change_not_offered(driver):
    driver.assert_email_change_not_offered()
