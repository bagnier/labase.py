from pytest_bdd import given, parsers, then, when


@given("the application is running", target_fixture="app")
def step_app_running(driver):
    driver.reset_session()


@given(
    parsers.parse('a user is registered with email "{email}" and password "{password}"'),
    target_fixture="app",
)
def step_user_registered(driver, email, password):
    driver.reset_session()
    driver.ensure_registered(email, password)


@given(
    parsers.parse('a user is signed in as "{email}" with password "{password}"'),
    target_fixture="app",
)
def step_user_signed_in(driver, email, password):
    driver.reset_session()
    driver.ensure_registered(email, password)
    driver.sign_in(email, password)


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
    driver.visit("/dashboard")


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


# --- Auth (generic) ---


@given("a user is signed in", target_fixture="app")
def step_signed_in_fresh(driver):
    driver.reset_session()
    driver.sign_in_as_fresh_user()


# --- Dashboard ---


@when("they view the dashboard")
def step_view_dashboard(driver):
    driver.view_dashboard()


@then("there is a link to their todo list")
def step_link_to_todos(driver):
    driver.assert_link_to_todos()


# --- Todo ---


@given(parsers.parse("they have todo items {titles}"))
def step_have_todo_items(driver, titles):
    items = [t.strip().strip('"') for t in titles.split(",")]
    driver.have_todo_items(items)


@given(parsers.parse('they have a todo item "{title}"'))
def step_have_todo_item(driver, title):
    driver.have_todo_items([title])


@when("they view their todo list")
def step_view_todo_list(driver):
    driver.view_todo_list()


@when(parsers.parse('they add a todo item "{title}"'))
def step_add_todo(driver, title):
    driver.add_todo(title)


@when(parsers.parse('they mark "{title}" as done'))
def step_mark_todo_done(driver, title):
    driver.mark_todo_done(title)


@when(parsers.parse('they rename "{title}" to "{new_title}"'))
def step_rename_todo(driver, title, new_title):
    driver.rename_todo(title, new_title)


@when(parsers.parse('they delete "{title}"'))
def step_delete_todo(driver, title):
    driver.delete_todo(title)


@when(parsers.parse('they move "{title}" above "{above}"'))
def step_move_todo_above(driver, title, above):
    driver.move_todo_above(title, above)


@when(parsers.parse('they move "{title}" to the end'))
def step_move_todo_to_end(driver, title):
    driver.move_todo_to_end(title)


@then(parsers.parse("the items appear in order: {titles}"))
def step_assert_todo_order(driver, titles):
    items = [t.strip().strip('"') for t in titles.split(",")]
    driver.assert_todo_list_order(items)


@then(parsers.parse('"{title}" appears in their todo list'))
def step_assert_todo_visible(driver, title):
    driver.assert_todo_visible(title)


@then(parsers.parse('"{title}" is shown as completed'))
def step_assert_todo_completed(driver, title):
    driver.assert_todo_completed(title)


@then(parsers.parse('"{title}" no longer appears in their todo list'))
def step_assert_todo_absent(driver, title):
    driver.assert_todo_absent(title)
