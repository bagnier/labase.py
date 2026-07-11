"""Cross-cutting BDD steps shared by every app.

Registered once via ``pytest_plugins`` in ``tests/plugin.py`` so these phrases
reach every scenario, the same way the ``driver`` fixture does — no app needs to
re-declare them. The bodies dispatch to helpers on the driver base classes
(``ApiBase`` / ``BrowserBase``): the *phrase* is shared, each driver keeps its
own way of reading the last response.
"""

from pytest_bdd import parsers, then


@then("the action is forbidden")
def step_action_forbidden(driver):
    driver.assert_forbidden()


@then(parsers.parse("the {target} is not found"))
def step_not_found(driver, target):
    """Admin-only surfaces answer a non-admin with a plain 404, never a 403 — the
    surface must not even reveal its existence. ``target`` (console, accounts
    screen, logs screen, …) is documentary; the assertion is the same everywhere.
    """
    driver.assert_not_found()
