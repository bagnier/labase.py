"""What a column sort actually sorts — and the timeline saying so.

The reader asks each of its three sources for *its own* newest rows, merges them, sorts and cuts
to the page size. On the default ``ts`` sort that is exact: the newest hundred overall can only
come from the newest hundred of each source. On any other column it is not — sorting by name
ascending returns the alphabetically first hundred *of a recent sample*, never of the timeline.

Fixing that means sorting in each source, which the firehose (a file) cannot do without reading
all of it. Until the sources are one queryable store, the honest move is to keep the sort and say
what it covers, rather than to present a sample as an ordering.
"""

_ADMIN = "sort-honesty@example.com"


def _timeline(driver, query: str) -> str:
    return driver.client().get(f"/console/timeline{query}", headers={"accept": "text/html"}).text


def test_the_default_sort_claims_nothing(driver):
    """Newest-first over the whole window is exactly what it looks like — no caveat to give."""
    driver.sign_in_as_admin(_ADMIN)

    assert "data-sort-scope" not in _timeline(driver, "")


def test_a_column_sort_says_it_only_orders_the_page(driver):
    """Silence here reads as "these are the first hundred by name", which they are not."""
    driver.sign_in_as_admin(_ADMIN)

    assert "data-sort-scope" in _timeline(driver, "?sort=name")
