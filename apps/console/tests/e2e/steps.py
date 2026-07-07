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


@then(parsers.parse('a Supabase link pointing at "{fragment}" is shown for the "{app}" app'))
def step_supabase_link_shown(driver, fragment, app):
    driver.assert_console_supabase_link(app, fragment)


@when(
    parsers.parse('the admin overrides the "{app}" setting "{key}" to "{value}" for the active org')
)
def step_admin_sets_org_override(driver, app, key, value):
    driver.set_org_override(app, key, value)


@then(parsers.parse('the "{app}" override "{key}" for the active org is listed as "{value}"'))
def step_assert_org_override_listed(driver, app, key, value):
    driver.assert_org_override_listed(app, key, value)


# ── Server admins ──────────────────────────────────────────────────────────────
# Reuses the org "the action is forbidden" step for the last-admin guard.


@given("the server has no admin yet")
def step_no_admin_yet(driver):
    driver.ensure_no_server_admin()


@given("the server already has an admin")
def step_server_has_admin(driver):
    driver.seed_existing_admin()


@given(parsers.parse('"{email}" is the first registered user'))
@when(parsers.parse('"{email}" registers'))
def step_registers(driver, email):
    driver.register_and_sign_in(email)


@given(parsers.parse('"{email}" has registered'))
def step_has_registered(driver, email):
    driver.register_regular_user(email)


@given(parsers.parse('"{email}" is a server admin'))
def step_is_server_admin(driver, email):
    driver.register_regular_user(email)
    driver.designate_server_admin(email)


@then(parsers.parse('"{email}" can open the console'))
def step_can_open_console(driver, email):
    driver.assert_can_open_console(email)


@then(parsers.parse('"{email}" is refused access to the console'))
def step_refused_console(driver, email):
    driver.assert_refused_console(email)


@when("the admin opens the admins page on the console")
def step_open_admins_page(driver):
    driver.open_admins_page()


@then(parsers.parse('"{email}" appears in the admin list as a server admin'))
def step_appears_as_admin(driver, email):
    driver.assert_admin_list_status(email, is_admin=True)


@then(parsers.parse('"{email}" appears in the admin list as a regular user'))
def step_appears_as_regular(driver, email):
    driver.assert_admin_list_status(email, is_admin=False)


@then(parsers.parse('"{email}" does not appear in the admin list'))
def step_absent_from_admin_list(driver, email):
    driver.assert_email_absent_from_admin_list(email)


@given(parsers.parse('the admin adds "{email}" as a server admin by email'))
@when(parsers.parse('the admin adds "{email}" as a server admin by email'))
def step_add_by_email(driver, email):
    driver.add_server_admin_by_email(email)


@then(parsers.parse('the admins page reports that no account exists for "{email}"'))
def step_add_unknown_error(driver, email):
    driver.assert_admin_add_error(email)


@given(parsers.parse('the admin designates "{email}" as a server admin'))
@when(parsers.parse('the admin designates "{email}" as a server admin'))
def step_designate(driver, email):
    driver.designate_server_admin(email)


@when(parsers.parse('the admin revokes the server admin rights of "{email}"'))
def step_revoke(driver, email):
    driver.revoke_server_admin(email)


@when(parsers.parse('"{email}" signs in again'))
def step_signs_in_again(driver, email):
    driver.sign_in_again(email)


@when(parsers.parse('they try to designate "{email}" as a server admin'))
def step_try_designate(driver, email):
    driver.try_designate_server_admin(email)
