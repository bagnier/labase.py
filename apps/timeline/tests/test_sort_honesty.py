"""What a column sort actually sorts — and the timeline saying so.

The reader asks each of its three sources for *its own* newest rows, merges them, sorts and cuts
to the page size. On the default newest-first ``ts`` sort that is exact: the newest hundred overall
can only come from the newest hundred of each source. On any other sort it is not — sorting by name
ascending returns the alphabetically first hundred *of a recent sample*, never of the timeline, and
sorting ``ts`` ascending only reverses that same recent sample, never reaching the window's true
oldest rows.

Fixing that means sorting in each source, which the log sink cannot do without reading
all of it. Until the sources are one queryable store, the honest move is to keep the sort and say
what it covers, rather than to present a sample as an ordering.
"""

import re

_ADMIN = "sort-honesty@example.com"


def _timeline(driver, query: str) -> str:
    return driver.client().get(f"/console/timeline{query}", headers={"accept": "text/html"}).text


def _notice_text(html: str) -> str:
    match = re.search(r"<p[^>]*data-sort-scope[^>]*>(.*?)</p>", html, re.DOTALL)
    assert match, "expected a data-sort-scope notice in the page"
    return " ".join(re.sub(r"<[^>]+>", "", match.group(1)).split())


def test_the_default_sort_claims_nothing(driver):
    """Newest-first over the whole window is exactly what it looks like — no caveat to give."""
    driver.sign_in_as_admin(_ADMIN)

    assert "data-sort-scope" not in _timeline(driver, "")


def test_a_column_sort_says_it_only_orders_the_page(driver):
    """Silence here reads as "these are the first hundred by name", which they are not."""
    driver.sign_in_as_admin(_ADMIN)

    assert "data-sort-scope" in _timeline(driver, "?sort=name")


def test_ascending_time_says_it_only_orders_the_page(driver):
    """Each source is asked for its own *newest* rows regardless of direction, so ascending
    time sorts a recent sample backwards rather than reaching the window's true oldest rows —
    the same caveat the other non-exact sorts already carry."""
    driver.sign_in_as_admin(_ADMIN)

    assert "data-sort-scope" in _timeline(driver, "?sort=ts&dir=asc")


def test_ascending_time_does_not_claim_time_is_exact(driver):
    """The generic notice says "only time orders the whole window" — true while some other
    column is sorted, false here, since time is exactly what is sorted and it is still only
    a sample: the wording has to name what actually went wrong for this column."""
    driver.sign_in_as_admin(_ADMIN)

    text = _notice_text(_timeline(driver, "?sort=ts&dir=asc"))

    assert text == (
        "Sorted oldest-first within the loaded page — each source's own newest rows, "
        "reversed, not the window's true oldest. Back to newest first, or narrow with a "
        "filter to sort a smaller set exactly."
    )
