"""``CachingStaticFiles`` adds the public, content-aware ``Cache-Control`` that Starlette's
``StaticFiles`` omits: fingerprinted URLs are immutable, the rest get a tunable TTL, and a
zero TTL degrades to revalidate-every-time. ETag/304 (Starlette's job) is untouched."""

import pytest

from apps.shared.http.static import CachingStaticFiles


def _scope(query: bytes = b"") -> dict:
    return {"type": "http", "query_string": query}


@pytest.mark.parametrize(
    ("query", "max_age", "expected"),
    [
        (b"v=123", 3600, "public, max-age=31536000, immutable"),  # fingerprinted → immutable
        (b"", 3600, "public, max-age=3600"),  # plain asset → tunable TTL
        (b"", 0, "public, max-age=0, must-revalidate"),  # dev → always revalidate
        (b"v=1", 0, "public, max-age=31536000, immutable"),  # fingerprint wins over TTL=0
    ],
)
def test_cache_control_branches(query, max_age, expected):
    files = CachingStaticFiles(directory=".", max_age=max_age, check_dir=False)
    assert files._cache_control(_scope(query)) == expected


def test_a_non_v_query_is_not_treated_as_fingerprinted():
    files = CachingStaticFiles(directory=".", max_age=60, check_dir=False)
    assert files._cache_control(_scope(b"foo=bar")) == "public, max-age=60"
