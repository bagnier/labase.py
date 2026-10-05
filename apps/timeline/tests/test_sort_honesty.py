"""Only newest-first is exact; any other sort orders each source's newest rows, and the screen
says so."""

import re

_ADMIN = "sort-honesty@example.com"


def _timeline(driver, query: str) -> str:
    return driver.client().get(f"/console/timeline{query}", headers={"accept": "text/html"}).text


def _notice_text(html: str) -> str:
    match = re.search(r"<p[^>]*data-sort-scope[^>]*>(.*?)</p>", html, re.DOTALL)
    assert match, "expected a data-sort-scope notice in the page"
    return " ".join(re.sub(r"<[^>]+>", "", match.group(1)).split())


def test_the_default_sort_claims_nothing(driver):
    driver.sign_in_as_admin(_ADMIN)

    assert "data-sort-scope" not in _timeline(driver, "")


def test_a_column_sort_says_it_only_orders_the_page(driver):
    driver.sign_in_as_admin(_ADMIN)

    assert "data-sort-scope" in _timeline(driver, "?sort=name")


def test_ascending_time_says_it_only_orders_the_page(driver):
    """Ascending time reverses the newest rows; it never reaches the oldest."""
    driver.sign_in_as_admin(_ADMIN)

    assert "data-sort-scope" in _timeline(driver, "?sort=ts&dir=asc")


def test_ascending_time_does_not_claim_time_is_exact(driver):
    """The generic notice ("only time orders the whole window") would be wrong here."""
    driver.sign_in_as_admin(_ADMIN)

    text = _notice_text(_timeline(driver, "?sort=ts&dir=asc"))

    assert text == (
        "Sorted oldest-first within the loaded page — each source's own newest rows, "
        "reversed, not the window's true oldest. Back to newest first, or narrow with a "
        "filter to sort a smaller set exactly."
    )
