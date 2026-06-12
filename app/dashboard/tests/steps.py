from pytest_bdd import then, when


@when("they view the dashboard")
def step_view_dashboard(driver):
    driver.view_dashboard()


@then("there is a link to their todo list")
def step_link_to_todos(driver):
    driver.assert_link_to_todos()


@when("they view the profile")
def step_view_profile(driver):
    driver.view_profile()


@then("there is a link to their org dashboard")
def step_link_to_org_dashboard(driver):
    driver.assert_link_to_org_dashboard()


@when("they try to access the profile without signing in")
def step_access_profile_unauthenticated(driver):
    driver.visit_profile_unauthenticated()


@when("they try to access an org dashboard without signing in")
def step_access_org_dashboard_unauthenticated(driver):
    driver.visit_org_dashboard_unauthenticated()


@when("they try to access the console without signing in")
def step_access_console_unauthenticated(driver):
    driver.visit_console_unauthenticated()


@when("they view their org dashboard")
def step_view_org_dashboard(driver):
    driver.view_org_dashboard()


@then("the org dashboard is visible")
def step_org_dashboard_visible(driver):
    driver.assert_org_dashboard_visible()
