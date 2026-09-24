"""A GoTrue outage on the profile's password/email change must reach the dependency verdict
as a bug, not be swallowed by the "wrong current password" branch, which used to catch every
``PasswordUpdateError``/``EmailChangeError`` and log nothing (issue #106, same as #52)."""

from unittest.mock import patch

from apps.auth.contract.email_change import EmailChangeError
from apps.auth.contract.passwords import PasswordUpdateError

_EMAIL = "password-email-change-dependency@example.com"


def test_password_change_gotrue_outage_is_logged_not_silent(driver):
    client = driver.client_for(_EMAIL)
    outage = PasswordUpdateError("Service Unavailable", 503)

    with (
        patch("apps.profile.infra.router.change_password", side_effect=outage),
        patch("apps.profile.infra.router.log") as log,
    ):
        response = client.post(
            "/profile/password",
            json={"current_password": "Test1234!", "new_password": "NewPass1!"},
            headers={"accept": "application/json"},
        )

    assert response.status_code == 400
    log.exception.assert_called_once_with("profile.password_change_failed", exc_info=outage)


def test_password_change_refused_returns_400_without_opening_an_issue(driver):
    client = driver.client_for(_EMAIL)
    refused = PasswordUpdateError("Weak password", 400)

    with (
        patch("apps.profile.infra.router.change_password", side_effect=refused),
        patch("apps.profile.infra.router.log") as log,
    ):
        response = client.post(
            "/profile/password",
            json={"current_password": "Test1234!", "new_password": "NewPass1!"},
            headers={"accept": "application/json"},
        )

    assert response.status_code == 400
    assert "weak password" in response.text.lower()
    log.exception.assert_not_called()


def test_email_change_gotrue_outage_is_logged_not_silent(driver):
    client = driver.client_for(_EMAIL)
    outage = EmailChangeError("Service Unavailable", 503)

    with (
        patch("apps.profile.infra.router.change_email", side_effect=outage),
        patch("apps.profile.infra.router.log") as log,
    ):
        response = client.post(
            "/profile/email",
            json={"current_password": "Test1234!", "new_email": "new@example.com"},
            headers={"accept": "application/json"},
        )

    assert response.status_code == 400
    log.exception.assert_called_once_with("profile.email_change_failed", exc_info=outage)


def test_email_change_refused_returns_400_without_opening_an_issue(driver):
    client = driver.client_for(_EMAIL)
    refused = EmailChangeError("Email address already in use", 400)

    with (
        patch("apps.profile.infra.router.change_email", side_effect=refused),
        patch("apps.profile.infra.router.log") as log,
    ):
        response = client.post(
            "/profile/email",
            json={"current_password": "Test1234!", "new_email": "new@example.com"},
            headers={"accept": "application/json"},
        )

    assert response.status_code == 400
    assert "already in use" in response.text.lower()
    log.exception.assert_not_called()
