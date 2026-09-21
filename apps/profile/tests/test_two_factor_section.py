"""The profile's 2FA section — its state is read from GoTrue, which can fail."""

from unittest.mock import patch

import httpx

from apps.auth.contract.two_factor import AuthTokens
from apps.auth.tests.test_oauth_callback import _two_factor_enabled

_EMAIL = "two-factor-section@example.com"


def test_confirming_an_enrolment_hands_over_the_upgraded_session(driver):
    """Once enrolled, an aal1 token is refused: the session that confirmed the code must be the
    aal2 one GoTrue returns, or the enrolment signs its own author out."""
    client = driver.client_for(_EMAIL)
    upgraded = AuthTokens(access_token="aal2-access", refresh_token="aal2-refresh")

    with (
        _two_factor_enabled(),
        patch("apps.profile.infra.router.totp_challenge", return_value="challenge"),
        patch("apps.profile.infra.router.verify_totp", return_value=upgraded),
    ):
        response = client.post(
            "/profile/2fa/verify",
            json={"factor_id": "factor", "code": "123456"},
            headers={"accept": "application/json"},
        )

    assert (response.status_code, dict(response.cookies)) == (
        200,
        {"access_token": "aal2-access", "refresh_token": "aal2-refresh"},
    )


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
