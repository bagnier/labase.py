from pytest_bdd import given, parsers, then, when


@given("the application is running")
def step_app_running(driver):
    driver.reset_session()


@given(parsers.parse('a user is signed in as "{email}" within org "{org_name}"'))
def step_user_signed_in_within_org(driver, email, org_name):
    driver.reset_session()
    driver.sign_in_within_org(email, org_name)


@given(parsers.parse('a user is signed in as "{email}" as owner of "{org_name}"'))
def step_user_signed_in_as_owner_of(driver, email, org_name):
    driver.reset_session()
    driver.sign_in_within_org(email, org_name)


@given(parsers.parse('a user is registered with email "{email}" and password "{password}"'))
def step_user_registered(driver, email, password):
    driver.reset_session()
    driver.register_disposable(email, password)
    driver._last_registered_email = email


@given(parsers.parse('a user is signed in as "{email}" with password "{password}"'))
def step_user_signed_in(driver, email, password):
    driver.reset_session()
    driver.ensure_registered(email, password)
    driver.sign_in(email, password)


@given("a user is signed in")
def step_signed_in_fresh(driver):
    driver.reset_session()
    driver.sign_in_as_fresh_user()


@when(parsers.parse('they sign in with email "{email}" and password "{password}"'))
def step_sign_in(driver, email, password):
    driver.sign_in(email, password)


@when(parsers.parse('they register with email "{email}" and password "{password}"'))
def step_register(driver, email, password):
    driver.register(email, password)


@when(parsers.parse('they register with a new email and password "{password}"'))
def step_register_fresh(driver, password):
    driver.register_fresh(password)


@when(parsers.parse('they register with a "{email}" and password "{password}"'))
def step_register_disposable(driver, email, password):
    driver.register_disposable(email, password)


@when("they try to access the dashboard without signing in")
def step_access_dashboard_unauthenticated(driver):
    driver.visit("/profile")


@when("they access the home page without signing in")
def step_access_home_unauthenticated(driver):
    driver.visit("/")


@when("they sign out")
def step_sign_out(driver):
    driver.logout_action()


@then("the sign-in form is available")
def step_sign_in_form_available(driver):
    driver.assert_page_accessible("/auth/login", "Connexion")


@then("the registration form is available")
def step_registration_form_available(driver):
    driver.assert_page_accessible("/auth/register", "Créer un compte")


@then("they are on their dashboard")
def step_on_dashboard(driver):
    driver.assert_redirected_to_dashboard()


@then("their sign-in is rejected")
def step_sign_in_rejected(driver):
    driver.assert_login_rejected()


@then("access is denied")
def step_access_denied(driver):
    driver.assert_unauthorized()


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
