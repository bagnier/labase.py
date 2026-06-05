from pytest_bdd import given, parsers, then, when


@given("the app is running", target_fixture="app")
def step_app_running():
    pass


@then("the login page is accessible")
def step_login_page_accessible(driver):
    driver.assert_page_accessible("/auth/login", "Connexion")


@then("the register page is accessible")
def step_register_page_accessible(driver):
    driver.assert_page_accessible("/auth/register", "Créer un compte")


@when(parsers.parse('I log in with email "{email}" and password "{password}"'))
def step_login(driver, email, password):
    driver.login(email, password)


@when("I visit the dashboard without logging in")
def step_visit_dashboard_no_auth(driver):
    driver.visit("/dashboard")


@when("I visit the home page without logging in")
def step_visit_home_no_auth(driver):
    driver.visit("/")


@then("my login attempt is rejected")
def step_login_rejected(driver):
    driver.assert_login_rejected()


@then("I am not authorized")
def step_not_authorized(driver):
    driver.assert_unauthorized()


@then("I am redirected to login")
def step_redirected_to_login(driver):
    driver.assert_redirected_to_login()


@then("the page loads successfully")
def step_page_loads(driver):
    driver.assert_page_loaded()
