from pytest_bdd import given, parsers, then, when


@given("the application is running")
def step_app_running():
    """Session reset is centralised in the db_rollback fixture; nothing to do here."""


@given(parsers.parse('a user is signed in as "{email}" within org "{org_name}"'))
def step_user_signed_in_within_org(driver, email, org_name):
    driver.sign_in_within_org(email, org_name)


@given(parsers.parse('a user is signed in as "{email}" as owner of "{org_name}"'))
def step_user_signed_in_as_owner_of(driver, email, org_name):
    driver.sign_in_within_org(email, org_name)


@given(parsers.parse('a user is registered with email "{email}" and password "{password}"'))
def step_user_registered(driver, email, password):
    driver.register_disposable(email, password)


@given(parsers.parse('a user is signed in as "{email}"'))
def step_user_signed_in_email_only(driver, email):
    driver.ensure_registered(email, "Test1234!")
    driver.sign_in(email, "Test1234!")


@given(parsers.parse('a user is signed in as "{email}" with password "{password}"'))
def step_user_signed_in(driver, email, password):
    driver.ensure_registered(email, password)
    driver.sign_in(email, password)


@given("a user is signed in")
def step_signed_in_fresh(driver):
    driver.sign_in_as_fresh_user()


@given(parsers.parse('a visitor signs in with email "{email}" and password "{password}"'))
@when(parsers.parse('a visitor signs in with email "{email}" and password "{password}"'))
def step_visitor_sign_in(driver, email, password):
    driver.sign_in(email, password)


@when(parsers.parse('a visitor registers with "{email}" and password "{password}"'))
def step_visitor_register(driver, email, password):
    driver.register(email, password)


@when(parsers.parse('a visitor registers with a new email and password "{password}"'))
def step_visitor_register_fresh(driver, password):
    driver.register_fresh(password)


@when("they try to access their profile without signing in")
def step_access_profile_unauthenticated(driver):
    driver.visit("/profile")


@when("they access the home page without signing in")
def step_access_home_unauthenticated(driver):
    driver.visit("/")


@when("they sign out")
def step_sign_out(driver):
    driver.logout_action()


@when(parsers.parse('they request a password reset for "{email}"'))
def step_request_password_reset(driver, email):
    driver.request_password_reset(email)


@when(parsers.parse('they set a new password "{password}" using the emailed reset link'))
def step_reset_password_via_email(driver, password):
    driver.reset_password_via_email(password)


@when(parsers.parse('they change their password from "{current}" to "{new}"'))
def step_change_password(driver, current, new):
    driver.change_password(current, new)


@then("the sign-in form is available")
def step_sign_in_form_available(driver):
    driver.assert_page_accessible("/auth/login", "Sign in")


@then("the registration form is available")
def step_registration_form_available(driver):
    driver.assert_page_accessible("/auth/register", "Create an account")


@given("they are on their profile page")
@then("they are on their profile page")
def step_on_profile(driver):
    driver.assert_redirected_to_dashboard()


@then("their sign-in is rejected")
def step_sign_in_rejected(driver):
    driver.assert_login_rejected()


@then("access is denied")
def step_access_denied(driver):
    driver.assert_redirected_to_login()


@then("they are asked to verify their email")
def step_verify_email(driver):
    driver.assert_registration_successful()


@then("their registration is rejected")
def step_registration_rejected(driver):
    driver.assert_registration_failed()


@then(parsers.parse('their registration is rejected with message "{message}"'))
def step_registration_rejected_with_message(driver, message):
    driver.assert_registration_failed_with_message(message)


@then("they are redirected to sign-in")
def step_redirected_to_sign_in(driver):
    driver.assert_redirected_to_login()


@then("it is publicly accessible")
def step_publicly_accessible(driver):
    driver.assert_page_loaded()


@when(parsers.parse('the admin impersonates "{email}"'))
def step_admin_impersonates(driver, email):
    driver.impersonate(email)


@then(parsers.parse('they are viewing the app as "{email}"'))
def step_assert_viewing_as(driver, email):
    driver.assert_viewing_as(email)


@then("the impersonation banner is visible")
def step_assert_impersonation_banner(driver):
    driver.assert_impersonation_banner()


@when("they stop impersonating")
def step_stop_impersonating(driver):
    driver.stop_impersonating()


@then(parsers.parse('they are back on their admin account "{email}"'))
def step_assert_back_as_admin(driver, email):
    driver.assert_back_as_admin(email)


@when(parsers.parse('they try to impersonate "{email}"'))
def step_try_impersonate(driver, email):
    driver.try_impersonate(email)


@then("the impersonation is refused")
def step_assert_impersonation_refused(driver):
    driver.assert_impersonation_refused()


@given(parsers.parse('an unconfirmed user is registered with email "{email}" and password "{pw}"'))
def step_unconfirmed_user_registered(driver, email, pw):
    driver.register_unconfirmed(email, pw)


@when(parsers.parse('they ask for the confirmation email to be resent to "{email}"'))
def step_resend_confirmation(driver, email):
    driver.resend_confirmation_to(email)


@then(parsers.parse('a confirmation link is delivered to "{email}"'))
def step_confirmation_delivered(driver, email):
    driver.assert_confirmation_delivered(email)


@when(parsers.parse('they confirm their address using the link emailed to "{email}"'))
def step_confirm_via_link(driver, email):
    driver.confirm_address_via_link(email)


@then(parsers.parse('their sign-in is rejected with message "{message}"'))
def step_sign_in_rejected_with(driver, message):
    driver.assert_login_rejected_with(message)


@then("they are offered to resend the confirmation email")
def step_resend_offered(driver):
    driver.assert_resend_offered()


@then("they are not offered to resend the confirmation email")
def step_resend_not_offered(driver):
    driver.assert_resend_not_offered()


@when("the admin opens the accounts screen")
def step_open_accounts_screen(driver):
    driver.open_accounts_screen()


@then(parsers.parse('the account "{email}" is listed'))
def step_assert_account_listed(driver, email):
    driver.assert_account_listed(email)


@then(parsers.parse('the account "{email}" is no longer listed'))
def step_assert_account_not_listed(driver, email):
    driver.assert_account_not_listed(email)


@when(parsers.parse('the admin disables the account "{email}"'))
def step_disable_account(driver, email):
    driver.set_account_state(email, "disable")


@when(parsers.parse('the admin enables the account "{email}"'))
def step_enable_account(driver, email):
    driver.set_account_state(email, "enable")


@when(parsers.parse('the admin deletes the account "{email}"'))
def step_delete_account_console(driver, email):
    driver.set_account_state(email, "delete")


@when(parsers.parse('the admin filters the accounts by "{query}"'))
def step_filter_accounts(driver, query):
    driver.filter_accounts(query)


@then(parsers.parse('the account "{email}" stays listed after filtering'))
def step_assert_account_in_filtered(driver, email):
    driver.assert_account_in_filtered_list(email)


@then(parsers.parse('the account "{email}" is filtered out'))
def step_assert_account_filtered_out(driver, email):
    driver.assert_account_not_in_filtered_list(email)


@when("they try to open the accounts screen")
def step_try_open_accounts(driver):
    driver.try_open_accounts_screen()


@when("the admin tries to open the accounts screen")
def step_admin_tries_open_accounts(driver):
    driver.try_open_accounts_screen_as_admin()


@then("the accounts screen is not found")
def step_assert_accounts_not_found(driver):
    driver.assert_accounts_screen_not_found()


@given("they enrol an authenticator app")
@when("they enrol an authenticator app")
def step_enroll_totp(driver):
    driver.enroll_totp()


@then("their profile shows two-factor as enabled")
def step_assert_twofa_enabled(driver):
    driver.assert_twofa_enabled()


@then("they are asked for their authenticator code")
def step_assert_mfa_challenge(driver):
    driver.assert_mfa_challenge()


@when("they enter a valid authenticator code")
def step_enter_valid_code(driver):
    driver.enter_totp_code(None)


@when(parsers.parse('they enter the authenticator code "{code}"'))
def step_enter_code(driver, code):
    driver.enter_totp_code(code)


@then("the authenticator code is rejected")
def step_assert_code_rejected(driver):
    driver.assert_totp_rejected()


@then("the two-factor option is not offered")
def step_assert_twofa_not_offered(driver):
    driver.assert_twofa_not_offered()
