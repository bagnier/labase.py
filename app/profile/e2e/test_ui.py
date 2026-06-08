import pytest

from tests.e2e.drivers.browser import BrowserDriver

TEST_EMAIL = "ui-structure@labase.dev"
TEST_PASSWORD = "Test1234!"


@pytest.fixture(scope="session", autouse=True)
def _ensure_ui_user(browser_driver: BrowserDriver):
    browser_driver.ensure_registered(TEST_EMAIL, TEST_PASSWORD)


@pytest.fixture()
def page_auth(browser_driver: BrowserDriver):
    browser_driver.reset_session()
    browser_driver.sign_in(TEST_EMAIL, TEST_PASSWORD)
    return browser_driver


class TestProfilePage:
    def test_has_display_name_input(self, page_auth: BrowserDriver):
        page_auth.visit("/profile")
        assert page_auth._p.locator("input[name=display_name]").count() == 1

    def test_email_field_is_disabled(self, page_auth: BrowserDriver):
        page_auth.visit("/profile")
        disabled = page_auth._p.locator("input[disabled]")
        assert disabled.count() >= 1
        assert any(
            TEST_EMAIL in (disabled.nth(i).input_value() or "") for i in range(disabled.count())
        )

    def test_has_save_button(self, page_auth: BrowserDriver):
        page_auth.visit("/profile")
        assert page_auth._p.locator("button[type=submit]:has-text('Enregistrer')").count() == 1

    def test_has_danger_zone(self, page_auth: BrowserDriver):
        page_auth.visit("/profile")
        assert "Zone de danger" in page_auth._p.content()

    def test_delete_button_is_disabled(self, page_auth: BrowserDriver):
        page_auth.visit("/profile")
        assert page_auth._p.locator("button[disabled]").count() >= 1

    def test_shows_user_email(self, page_auth: BrowserDriver):
        page_auth.visit("/profile")
        assert TEST_EMAIL in page_auth._p.content()

    def test_has_logout_button(self, page_auth: BrowserDriver):
        page_auth.visit("/profile")
        assert page_auth._p.locator("button:has-text('Déconnexion')").count() == 1
