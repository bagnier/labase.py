"""OAuth callback and email-confirm routes, GoTrue mocked: session, TOTP step-up, failures. The
provider round-trip itself is tested by hand (docs/oauth.md)."""

from contextlib import contextmanager
from unittest.mock import patch

from supabase_auth.errors import AuthApiError

from apps.auth.domain.service import AuthTokens
from apps.shared.settings.live import get_settings

_TOKENS = AuthTokens(access_token="the-access-token", refresh_token="the-refresh-token")


@contextmanager
def _two_factor_enabled():
    """Set live ``users`` settings for one test, restoring them after."""
    handle = get_settings("users")
    before = handle._raw
    handle._raw = {**before, "two_factor_enabled": "true"}
    try:
        yield
    finally:
        handle._raw = before


def _callback(driver, **patches):
    client = driver.client()
    client.cookies.set("oauth_code_verifier", "the-verifier")
    client.cookies.set("oauth_next", "/profile")
    defaults = {
        "exchange_oauth_code": (_TOKENS, True),
        "decode_jwt": {"sub": "00000000-0000-0000-0000-000000000001"},
        "verified_totp_factor": None,
        "totp_challenge": "challenge-1",
    }
    defaults.update(patches)
    with (
        patch(
            "apps.auth.infra.router.exchange_oauth_code",
            return_value=defaults["exchange_oauth_code"],
        ),
        patch("apps.auth.infra.router.decode_jwt", return_value=defaults["decode_jwt"]),
        patch(
            "apps.auth.infra.router.verified_totp_factor",
            return_value=defaults["verified_totp_factor"],
        ),
        patch("apps.auth.infra.router.totp_challenge", return_value=defaults["totp_challenge"]),
    ):
        return client.get("/auth/callback?code=the-code", follow_redirects=False)


def test_callback_issues_the_session_and_clears_the_oauth_cookies(driver):
    response = _callback(driver)
    assert response.status_code == 303
    assert response.headers["location"] == "/profile"
    assert response.cookies.get("access_token") == _TOKENS.access_token
    set_cookie = ",".join(response.headers.get_list("set-cookie"))
    assert 'oauth_code_verifier=""' in set_cookie


def test_callback_with_totp_enrolled_asks_for_the_code_before_any_session(driver):
    """With 2FA on and a verified factor, the tokens wait for the challenge; no session yet."""
    with _two_factor_enabled():
        response = _callback(driver, verified_totp_factor="factor-1")
    assert response.status_code == 200
    assert "factor-1" in response.text
    assert "challenge-1" in response.text
    assert response.cookies.get("mfa_access_token") == _TOKENS.access_token
    assert response.cookies.get("access_token") is None
    set_cookie = ",".join(response.headers.get_list("set-cookie"))
    assert 'oauth_code_verifier=""' in set_cookie


def test_callback_with_totp_switched_on_but_not_enrolled_signs_straight_in(driver):
    with _two_factor_enabled():
        response = _callback(driver, verified_totp_factor=None)
    assert response.status_code == 303
    assert response.cookies.get("access_token") == _TOKENS.access_token


def test_callback_without_the_verifier_cookie_lands_back_on_login(driver):
    response = driver.client().get("/auth/callback?code=the-code", follow_redirects=False)
    assert response.status_code == 401
    assert "failed" in response.text.lower()


def test_confirm_failure_lands_on_login_with_a_visible_message(driver):
    """Every ``?info=`` key exists in ``_INFO_MESSAGES``."""
    from apps.auth.infra.router import _INFO_MESSAGES

    err = AuthApiError("Email link is invalid or has expired", 403, "otp_expired")
    client = driver.client()
    with patch("apps.auth.infra.router.confirm_signup", side_effect=err):
        response = client.post(
            "/auth/confirm", data={"token_hash": "dead", "type": "signup"}, follow_redirects=False
        )
    assert response.status_code == 303
    location = response.headers["location"]
    info_key = location.split("info=")[1]
    assert info_key in _INFO_MESSAGES
    landing = client.get(location)
    assert _INFO_MESSAGES[info_key] in landing.text


def test_opening_a_signup_link_spends_nothing_until_the_reader_confirms(driver):
    """(AGENTS: a GET never delivers a session)"""
    with patch("apps.auth.infra.router.confirm_signup", return_value=_TOKENS) as confirm:
        response = driver.client().get(
            "/auth/confirm?token_hash=the-hash&type=signup", follow_redirects=False
        )

    assert (response.cookies.get("access_token"), confirm.called) == (None, False)


def test_opening_an_email_change_link_spends_nothing_until_the_reader_confirms(driver):
    with patch("apps.auth.infra.router.confirm_signup", return_value=_TOKENS) as confirm:
        response = driver.client().get(
            "/auth/confirm-email?token_hash=the-hash", follow_redirects=False
        )

    assert (response.cookies.get("access_token"), confirm.called) == (None, False)
