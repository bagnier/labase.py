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


@pytest.fixture()
def page_auth(browser_driver: BrowserDriver):
    browser_driver.reset_session()
    browser_driver.sign_in(TEST_EMAIL, TEST_PASSWORD)
    return browser_driver


# ---------------------------------------------------------------------------
# Login page
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Register page
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Dashboard page
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Profile page
# ---------------------------------------------------------------------------


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
