"""The profile's 2FA section — its state is read from GoTrue, which can fail."""

from unittest.mock import patch

import httpx

from apps.auth.tests.test_oauth_callback import _two_factor_enabled

_EMAIL = "two-factor-section@example.com"


def test_a_factor_lookup_gotrue_fails_hides_the_section_instead_of_the_page(driver):
    """The section cannot say whether 2FA is on, so it says nothing; the rest of the page stands."""
    client = driver.client_for(_EMAIL)
    request = httpx.Request("GET", "http://gotrue/auth/v1/user")
    failed = httpx.HTTPStatusError("boom", request=request, response=httpx.Response(500))

    with (
        _two_factor_enabled(),
        patch("apps.profile.infra.router.verified_totp_factor", side_effect=failed),
    ):
        response = client.get("/profile", headers={"accept": "text/html"})

    assert (response.status_code, "data-twofa" in response.text) == (200, False)
