"""A failing full-page provider leaves its slice absent: the profile must not read it by key."""

from contextlib import contextmanager
from unittest.mock import patch

from apps.shared.integration.fullpage import FullpageQuery
from apps.shared.integration.host import FullpageProvider, host

_EMAIL = "org-nav-provider-failure@example.com"


async def _broken_org_nav(query: FullpageQuery) -> dict:
    raise RuntimeError("boom")


@contextmanager
def _org_nav_provider_broken():
    """The mounted ``org`` provider, replaced by one that raises."""
    broken = [
        FullpageProvider(p.name, p.keys, _broken_org_nav) if p.name == "org" else p
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
