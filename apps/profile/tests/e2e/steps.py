from pytest_bdd import given, parsers, then, when


@when("they try to access the profile without signing in")
def step_access_profile_unauthenticated(driver):
    driver.visit_profile_unauthenticated()


@then("their org dashboard is reachable from their profile")
def step_link_to_org_dashboard(driver):
    driver.assert_link_to_org_dashboard()


@when("they view the dashboard")
def step_view_dashboard(driver):
    driver.view_dashboard()


@then("their todo list is reachable from their profile")
def step_link_to_todos(driver):
    driver.assert_link_to_todos()


@then("their profile is reachable from the account area")
def step_profile_link_in_footer(driver):
    driver.assert_profile_link_in_footer()


@then("their profile is not in the main navigation")
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


@then("they cannot change their email from their profile")
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


@then(parsers.parse('the email change option is not offered to "{email}"'))
def step_assert_email_change_not_offered(driver, email):
    driver.assert_email_change_not_offered(email)


@when(parsers.parse('they delete their account confirming with password "{pw}"'))
def step_delete_account(driver, pw):
    driver.delete_account(pw)


@when(parsers.parse('"{email}" deletes their account'))
def step_delete_account_as(driver, email):
    """Names the actor — once a scenario has a second user on stage, "they" says nothing — and
    omits the password, which is the neighbouring scenarios' subject, not this one's."""
    driver.set_acting_email(email)
    driver.delete_account(driver.PASSWORD)


@then("the account deletion is rejected")
def step_assert_deletion_rejected(driver):
    driver.assert_account_deletion_rejected()


@then(parsers.parse('the account deletion option is not offered to "{email}"'))
def step_assert_deletion_not_offered(driver, email):
    driver.assert_account_deletion_not_offered(email)


@when("they upload a PNG image as their avatar")
def step_upload_avatar_png(driver):
    driver.upload_avatar("avatar.png", b"\x89PNG\r\n\x1a\nfake-image-bytes", "image/png")


@when("they upload a text file as their avatar")
def step_upload_avatar_text(driver):
    driver.upload_avatar("note.txt", b"not an image", "text/plain")


@then("their avatar is shown on their profile")
def step_assert_avatar_shown(driver):
    driver.assert_avatar_shown()


@then("the avatar upload is rejected")
def step_assert_avatar_rejected(driver):
    driver.assert_avatar_rejected()


@then(parsers.parse('the avatar option is not offered to "{email}"'))
def step_assert_avatar_not_offered(driver, email):
    driver.assert_avatar_not_offered(email)


@then(parsers.parse('the handle option is not offered to "{email}"'))
def step_assert_handle_not_offered(driver, email):
    driver.assert_handle_not_offered(email)
