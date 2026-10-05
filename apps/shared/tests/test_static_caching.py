"""``CachingStaticFiles``'s ``Cache-Control``."""

import pytest

from apps.shared.http.static import CachingStaticFiles


def _scope(query: bytes = b"") -> dict:
    return {"type": "http", "query_string": query}


@pytest.mark.parametrize(
    ("query", "max_age", "expected"),
    [
        (b"v=123", 3600, "public, max-age=31536000, immutable"),
        (b"", 3600, "public, max-age=3600"),
        (b"", 0, "public, max-age=0, must-revalidate"),
        (b"v=1", 0, "public, max-age=31536000, immutable"),
    ],
)
def test_cache_control_branches(query, max_age, expected):
    files = CachingStaticFiles(directory=".", max_age=max_age, check_dir=False)
    assert files._cache_control(_scope(query)) == expected


def test_a_non_v_query_is_not_treated_as_fingerprinted():
    files = CachingStaticFiles(directory=".", max_age=60, check_dir=False)
    assert files._cache_control(_scope(b"foo=bar")) == "public, max-age=60"
