import pytest
from playwright.sync_api import expect
from pytest_bdd import scenarios

from tests.e2e.drivers.browser import BrowserDriver

scenarios("../../../../features/todo.feature")


@pytest.fixture
def browser(driver) -> BrowserDriver:
    if not isinstance(driver, BrowserDriver):
        pytest.skip("browser-driver only: computed style and accessible name")
    return driver


def test_edit_and_delete_buttons_stay_visible_when_reached_by_keyboard(
    browser: BrowserDriver,
) -> None:
    browser.sign_in_as_fresh_user()
    browser.have_todo_items(["Buy groceries"])
    row = browser.page.locator("#todo-list > li:not([data-empty])").first
    checkbox = row.locator("input[data-todo-id]")
    edit_button = row.locator("[data-edit-id]")
    delete_button = row.locator("[data-delete-id]")

    checkbox.focus()
    browser.page.keyboard.press("Tab")
    expect(edit_button).to_have_css("opacity", "1")
    browser.page.keyboard.press("Tab")
    expect(delete_button).to_have_css("opacity", "1")


def test_rename_input_has_an_accessible_name(browser: BrowserDriver) -> None:
    browser.sign_in_as_fresh_user()
    browser.have_todo_items(["Buy groceries"])
    todo_id = browser._dom_todo_id_by_title("Buy groceries")

    browser.page.evaluate(f"startEdit('{todo_id}')")

    expect(browser.page.get_by_label("Rename “Buy groceries”")).to_be_visible()
