"""The profile page must survive a failing fullpage provider — fullpage.py isolates a provider
that raises (logged, skipped), so its slice can simply be absent from the context."""

from unittest.mock import patch

_EMAIL = "org-nav-provider-failure@example.com"


def test_profile_page_renders_when_the_org_nav_provider_fails(driver):
    client = driver.client_for(_EMAIL)

    with patch("apps.organizations.contract.fullpage.NavOrg", side_effect=RuntimeError("boom")):
        response = client.get("/profile", headers={"accept": "text/html"})

    assert (response.status_code, "data-organisation-card" in response.text) == (200, False)
