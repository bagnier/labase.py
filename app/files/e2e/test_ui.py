import os
import tempfile

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


def _org_files_url(driver: BrowserDriver) -> str:
    driver.visit("/dashboard")
    link = driver._p.locator("a[href*='/orgs/'][href*='/todos']").first
    todos_href = link.get_attribute("href") or ""  # /orgs/{slug}/todos
    return todos_href.rsplit("/todos", 1)[0] + "/files"  # /orgs/{slug}/files


class TestFilesPage:
    def test_delete_button_has_confirmation(self, page_auth: BrowserDriver):
        files_url = _org_files_url(page_auth)

        with tempfile.NamedTemporaryFile(
            suffix=".txt",
            dir="/Users/stephane/Codes/labase.py",
            delete=False,
        ) as f:
            f.write(b"e2e test content")
            tmppath = f.name

        try:
            page_auth.visit(files_url)
            page_auth._p.locator("input[type='file']").set_input_files(tmppath)
            with page_auth._p.expect_response(
                lambda r: "/files" in r.url and r.request.method == "POST", timeout=15000
            ):
                page_auth._p.get_by_role("button", name="Envoyer").click()

            page_auth.visit(files_url)
            btn = page_auth._p.locator("button[data-delete-id]").first
            assert btn.get_attribute("hx-confirm") is not None, (
                "Delete button is missing hx-confirm — file deleted without confirmation"
            )
        finally:
            os.unlink(tmppath)
