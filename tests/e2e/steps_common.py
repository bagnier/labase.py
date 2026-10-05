"""Steps shared by every app, registered in ``tests/plugin.py``; each driver base answers them."""

from pytest_bdd import parsers, then


@then("the action is forbidden")
def step_action_forbidden(driver):
    driver.assert_forbidden()


@then(parsers.parse("the {target} is not found"))
def step_not_found(driver, target):
    """A 404, never a 403 that would reveal the surface; ``target`` only documents."""
    driver.assert_not_found()
