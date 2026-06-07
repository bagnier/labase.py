from pytest_bdd import then, when


@when("they view the dashboard")
def step_view_dashboard(driver):
    driver.view_dashboard()


@then("there is a link to their todo list")
def step_link_to_todos(driver):
    driver.assert_link_to_todos()
