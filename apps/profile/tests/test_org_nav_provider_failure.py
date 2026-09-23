"""The profile page and its activity fragment must survive a failing fullpage provider —
fullpage_context isolates a provider that raises (logs, skips), so its slice can simply be
absent from the context; a route reading that slice by key turns the isolation back into a
KeyError 500 unless it reads it defensively."""

from contextlib import contextmanager
from unittest.mock import patch

from apps.shared.integration.fullpage import FullpageQuery
from apps.shared.integration.host import FullpageProvider, host

_EMAIL = "org-nav-provider-failure@example.com"


async def _broken_org_nav(query: FullpageQuery) -> dict:
    raise RuntimeError("boom")


@contextmanager
def _org_nav_provider_broken():
    """Swaps the mounted ``org`` fullpage provider for one that always raises — the same
    seam :func:`~apps.shared.integration.fullpage.fullpage_context` reads, so the isolation
    it promises is exercised for real rather than staged by patching an organizations
    internal."""
    broken = [
        FullpageProvider("org", _broken_org_nav) if p.name == "org" else p
        for p in host.fullpage_providers
    ]
    with patch.object(host, "fullpage_providers", broken):
        yield


def test_profile_page_renders_when_the_org_nav_provider_fails(driver):
    client = driver.client_for(_EMAIL)

    with _org_nav_provider_broken():
        response = client.get("/profile", headers={"accept": "text/html"})

    assert (response.status_code, "data-organisation-card" in response.text) == (200, False)


def test_profile_activity_fragment_renders_when_the_org_nav_provider_fails(driver):
    client = driver.client_for(_EMAIL)

    with _org_nav_provider_broken():
        response = client.get("/profile/activity", headers={"accept": "text/html"})

    assert response.status_code == 200
