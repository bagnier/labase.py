import pytest

from tests.e2e.drivers.browser import BrowserDriver

TEST_EMAIL = "ui-structure@labase.dev"
TEST_PASSWORD = "Test1234!"


@pytest.fixture(scope="session", autouse=True)
def _ensure_ui_user(browser_driver: BrowserDriver):
    browser_driver.ensure_registered(TEST_EMAIL, TEST_PASSWORD)


@pytest.fixture()
def page_anon(browser_driver: BrowserDriver):
    browser_driver.reset_session()
    return browser_driver


class TestLoginPage:
    def test_has_email_input(self, page_anon: BrowserDriver):
        page_anon.visit("/auth/login")
        assert page_anon._p.locator("input[name=email]").count() == 1

    def test_has_password_input(self, page_anon: BrowserDriver):
        page_anon.visit("/auth/login")
        assert page_anon._p.locator("input[name=password]").count() == 1

    def test_has_submit_button(self, page_anon: BrowserDriver):
        page_anon.visit("/auth/login")
        assert page_anon._p.locator("button[type=submit]").count() == 1

    def test_has_register_link(self, page_anon: BrowserDriver):
        page_anon.visit("/auth/login")
        assert page_anon._p.locator("a[href='/auth/register']").count() == 1

    def test_shows_error_on_bad_credentials(self, page_anon: BrowserDriver):
        page_anon.visit("/auth/login")
        page_anon._p.fill("input[name=email]", "bad@example.com")
        page_anon._p.fill("input[name=password]", "wrongpassword")
        with page_anon._p.expect_response(
            lambda r: "/auth/login" in r.url and r.request.method == "POST"
        ):
            page_anon._p.click("button[type=submit]")
        page_anon._p.wait_for_load_state("domcontentloaded")
        assert page_anon._p.locator("[class*='red']").count() > 0


class TestRegisterPage:
    def test_has_email_input(self, page_anon: BrowserDriver):
        page_anon.visit("/auth/register")
        assert page_anon._p.locator("input[name=email]").count() == 1

    def test_has_password_input(self, page_anon: BrowserDriver):
        page_anon.visit("/auth/register")
        assert page_anon._p.locator("input[name=password]").count() == 1

    def test_has_submit_button(self, page_anon: BrowserDriver):
        page_anon.visit("/auth/register")
        assert page_anon._p.locator("button[type=submit]").count() == 1

    def test_has_login_link(self, page_anon: BrowserDriver):
        page_anon.visit("/auth/register")
        assert page_anon._p.locator("a[href='/auth/login']").count() == 1
