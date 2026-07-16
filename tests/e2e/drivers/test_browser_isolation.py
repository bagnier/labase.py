"""Meta-tests for the browser driver's per-user session isolation.

Asserts that ``context_for(email)`` hands each email its own cookie jar (distinct
Playwright context), that ``page_for`` caches one page per email, and that the
acting-email switching and ``reset_session`` behave. Runs only under the browser
driver (skipped otherwise).
"""

import pytest

from tests.e2e.drivers.browser import BrowserDriver
from tests.e2e.drivers.browser_base import _VISITOR

_ALICE = "alice@example.com"
_BOB = "bob@example.com"


@pytest.fixture
def browser(driver) -> BrowserDriver:
    if not isinstance(driver, BrowserDriver):
        pytest.skip("browser-driver meta-test")
    return driver


def _email_on_profile(browser: BrowserDriver, email: str) -> str:
    page = browser.page_for(email)
    page.goto(f"{browser.base_url}/profile")
    page.wait_for_url("**/profile", timeout=10000)
    # The sign-in email lives read-only in the Email tab; open it before reading the field.
    page.get_by_role("tab", name="Email", exact=True).check()
    return page.locator("input#email").input_value()


def test_distinct_emails_get_isolated_contexts(browser: BrowserDriver) -> None:
    alice = browser.context_for(_ALICE)
    bob = browser.context_for(_BOB)

    assert alice is not bob
    assert _email_on_profile(browser, _ALICE) == _ALICE
    assert _email_on_profile(browser, _BOB) == _BOB


def test_context_and_page_are_cached_per_email(browser: BrowserDriver) -> None:
    assert browser.context_for(_ALICE) is browser.context_for(_ALICE)
    assert browser.page_for(_ALICE) is browser.page_for(_ALICE)


def test_visitor_context_is_unauthenticated(browser: BrowserDriver) -> None:
    page = browser.page_for(_VISITOR)
    page.goto(f"{browser.base_url}/profile")
    page.wait_for_url("**/auth/login**", timeout=10000)
    assert "/auth/login" in page.url


def test_page_follows_acting_email(browser: BrowserDriver) -> None:
    browser.context_for(_ALICE)

    browser.set_acting_email(_ALICE)
    assert browser.page is browser.page_for(_ALICE)
    assert browser.context is browser.context_for(_ALICE)

    browser.clear_acting_email()
    assert browser.context is browser.context_for(_VISITOR)


def test_sign_in_syncs_acting_email_with_the_authenticated_session(
    browser: BrowserDriver,
) -> None:
    """Guard the API/browser symmetry: sign_in must promote the acting user so the
    acting page is the one actually logged in — no orphan visitor context, no
    duplicate context for the same email."""
    email = "carol@example.com"
    browser.ensure_registered(email, "Secret1!")
    browser.sign_in(email, "Secret1!")

    assert browser._acting_email == email
    assert email in browser._contexts
    assert _VISITOR not in browser._contexts  # promoted, not duplicated
    assert _email_on_profile(browser, email) == email


def test_reset_session_reopens_a_fresh_visitor_context(browser: BrowserDriver) -> None:
    browser.context_for(_ALICE)
    browser.set_acting_email(_ALICE)

    browser.reset_session()

    assert set(browser._contexts) == {_VISITOR}
    assert browser._acting_email == _VISITOR
