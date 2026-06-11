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


class TestDashboardPage:
    def test_sidebar_has_dashboard_link(self, page_auth: BrowserDriver):
        page_auth.visit("/dashboard")
        assert page_auth._p.locator("a[href='/dashboard']").count() >= 1

    def test_sidebar_has_profile_link(self, page_auth: BrowserDriver):
        page_auth.visit("/dashboard")
        assert page_auth._p.locator("a[href='/profile']").count() >= 1

    def test_shows_utilisateurs_card(self, page_auth: BrowserDriver):
        page_auth.visit("/dashboard")
        assert "Utilisateurs" in page_auth._p.content()

    def test_shows_actifs_card(self, page_auth: BrowserDriver):
        page_auth.visit("/dashboard")
        assert "Actifs" in page_auth._p.content()

    def test_shows_revenus_card(self, page_auth: BrowserDriver):
        page_auth.visit("/dashboard")
        assert "Revenus" in page_auth._p.content()

    def test_shows_user_email(self, page_auth: BrowserDriver):
        page_auth.visit("/dashboard")
        assert TEST_EMAIL in page_auth._p.content()

    def test_has_logout_button(self, page_auth: BrowserDriver):
        page_auth.visit("/dashboard")
        assert page_auth._p.locator("button:has-text('Déconnexion')").count() == 1

    def test_has_link_to_todos(self, page_auth: BrowserDriver):
        page_auth.visit("/dashboard")
        assert page_auth._p.query_selector("a[href='/todos']") is not None

    def test_unauthenticated_access_redirects_to_login(self, browser_driver: BrowserDriver):
        browser_driver.reset_session()
        browser_driver.visit("/dashboard")
        assert "/auth/login" in browser_driver._p.url
