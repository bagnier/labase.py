import base64
import hashlib
import secrets
from dataclasses import dataclass
from typing import cast
from urllib.parse import urlencode

import httpx
import structlog
from supabase_auth.types import EmailOtpType, VerifyTokenHashParams

from apps.auth.contract.user import AuthenticatedUser as AuthenticatedUser
from apps.shared.config import get_technical_settings
from apps.shared.persistence.supabase import get_user_supabase

log = structlog.get_logger("labase.auth.service")


@dataclass
class AuthTokens:
    access_token: str
    refresh_token: str


async def login(email: str, password: str) -> AuthTokens:
    supabase = await get_user_supabase()
    auth = await supabase.auth.sign_in_with_password({"email": email, "password": password})
    if auth.session is None:
        raise ValueError("No session returned")
    return AuthTokens(
        access_token=auth.session.access_token,
        refresh_token=auth.session.refresh_token,
    )


async def logout(access_token: str) -> None:
    s = get_technical_settings()
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{s.supabase_api_url}/auth/v1/logout",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "apikey": s.supabase_publishable_key,
                },
            )
    except Exception:
        log.exception("auth.signout_failed")


async def refresh_session(refresh_token: str) -> AuthTokens:
    supabase = await get_user_supabase()
    auth = await supabase.auth.refresh_session(refresh_token)
    if auth.session is None:
        raise ValueError("Refresh failed")
    return AuthTokens(
        access_token=auth.session.access_token,
        refresh_token=auth.session.refresh_token,
    )


@dataclass
class RegisterResult:
    user_id: str
    access_token: str | None  # None when email confirmation is required


async def register(email: str, password: str) -> RegisterResult:
    """Signs up a new user. access_token is None when email confirmation is required."""
    supabase = await get_user_supabase()
    res = await supabase.auth.sign_up({"email": email, "password": password})
    if res.user is None:
        raise ValueError("Registration failed: no user returned")
    return RegisterResult(
        user_id=res.user.id,
        access_token=res.session.access_token if res.session else None,
    )


async def request_password_reset(email: str) -> None:
    """Ask GoTrue to send the recovery email (Supabase template, zero app mail code)."""
    supabase = await get_user_supabase()
    await supabase.auth.reset_password_for_email(email)


async def resend_confirmation(email: str) -> None:
    """Ask GoTrue to send the signup confirmation email again."""
    supabase = await get_user_supabase()
    await supabase.auth.resend({"type": "signup", "email": email})


OAUTH_PROVIDERS = ("google", "github")


class OAuthError(Exception):
    """GoTrue refused the OAuth operation; message is user-safe."""


def pkce_pair() -> tuple[str, str]:
    """A fresh PKCE (verifier, S256 challenge) pair.

    The app keeps no session between the redirect and the callback, so the
    verifier travels in a short-lived httpOnly cookie — the MFA parking pattern.
    """
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def oauth_authorize_url(provider: str, redirect_to: str, code_challenge: str) -> str:
    """The GoTrue authorize URL the browser is sent to — GoTrue drives the provider."""
    s = get_technical_settings()
    query = urlencode(
        {
            "provider": provider,
            "redirect_to": redirect_to,
            "code_challenge": code_challenge,
            "code_challenge_method": "s256",
        }
    )
    return f"{s.supabase_api_url}/auth/v1/authorize?{query}"


async def exchange_oauth_code(code: str, code_verifier: str) -> AuthTokens:
    """PKCE code-for-session exchange — stateless, like every GoTrue call here."""
    s = get_technical_settings()
    async with httpx.AsyncClient() as client:
        res = await client.post(
            f"{s.supabase_api_url}/auth/v1/token?grant_type=pkce",
            headers={"apikey": s.supabase_publishable_key},
            json={"auth_code": code, "code_verifier": code_verifier},
        )
    if res.status_code >= 400:
        try:
            body = res.json()
            message = body.get("error_description") or body.get("msg") or ""
        except ValueError:
            message = ""
        raise OAuthError(message or "Sign-in with the provider failed.")
    data = res.json()
    return AuthTokens(access_token=data["access_token"], refresh_token=data["refresh_token"])


class TotpError(Exception):
    """GoTrue refused the TOTP operation; message is user-safe."""


@dataclass(frozen=True)
class TotpEnrollment:
    factor_id: str
    secret: str
    uri: str


async def _factors_request(method: str, path: str, access_token: str, json: dict) -> dict:
    """Stateless GoTrue MFA call (like update_password) — the supabase-py MFA
    client wants a stateful session we deliberately don't keep."""
    s = get_technical_settings()
    async with httpx.AsyncClient() as client:
        res = await client.request(
            method,
            f"{s.supabase_api_url}/auth/v1/factors{path}",
            headers={
                "Authorization": f"Bearer {access_token}",
                "apikey": s.supabase_publishable_key,
            },
            json=json,
        )
    if res.status_code >= 400:
        try:
            message = res.json().get("msg", "Two-factor operation failed.")
        except ValueError:
            message = "Two-factor operation failed."
        raise TotpError(message)
    return res.json()


async def enroll_totp(access_token: str) -> TotpEnrollment:
    data = await _factors_request(
        "POST", "", access_token, {"factor_type": "totp", "friendly_name": "authenticator"}
    )
    return TotpEnrollment(
        factor_id=data["id"], secret=data["totp"]["secret"], uri=data["totp"]["uri"]
    )


async def totp_challenge(access_token: str, factor_id: str) -> str:
    data = await _factors_request("POST", f"/{factor_id}/challenge", access_token, {})
    return data["id"]


async def verify_totp(
    access_token: str, factor_id: str, challenge_id: str, code: str
) -> AuthTokens:
    """A correct code upgrades the session (AAL2) — GoTrue returns fresh tokens."""
    data = await _factors_request(
        "POST", f"/{factor_id}/verify", access_token, {"challenge_id": challenge_id, "code": code}
    )
    return AuthTokens(access_token=data["access_token"], refresh_token=data["refresh_token"])


async def verified_totp_factor(access_token: str) -> str | None:
    """The id of the account's verified TOTP factor, if any (drives the login step-up)."""
    s = get_technical_settings()
    async with httpx.AsyncClient() as client:
        res = await client.get(
            f"{s.supabase_api_url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "apikey": s.supabase_publishable_key,
            },
        )
    if res.status_code >= 400:
        return None
    for factor in res.json().get("factors") or []:
        if factor.get("factor_type") == "totp" and factor.get("status") == "verified":
            return str(factor.get("id"))
    return None


class PasswordUpdateError(Exception):
    """GoTrue refused the new password (typically weak_password); message is user-safe."""


async def update_password(access_token: str, new_password: str) -> None:
    """Set a new password for the session's user — stateless GoTrue call, like logout()."""
    s = get_technical_settings()
    async with httpx.AsyncClient() as client:
        res = await client.put(
            f"{s.supabase_api_url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "apikey": s.supabase_publishable_key,
            },
            json={"password": new_password},
        )
    if res.status_code >= 400:
        try:
            message = res.json().get("msg", "Password update failed.")
        except ValueError:
            message = "Password update failed."
        raise PasswordUpdateError(message)


class EmailChangeError(Exception):
    """GoTrue refused the email change (invalid or taken address); message is user-safe."""


async def request_email_change(access_token: str, new_email: str) -> None:
    """Ask GoTrue to mail a confirmation to the new address — stateless, like update_password."""
    s = get_technical_settings()
    async with httpx.AsyncClient() as client:
        res = await client.put(
            f"{s.supabase_api_url}/auth/v1/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "apikey": s.supabase_publishable_key,
            },
            json={"email": new_email},
        )
    if res.status_code >= 400:
        try:
            message = res.json().get("msg", "Email change failed.")
        except ValueError:
            message = "Email change failed."
        raise EmailChangeError(message)


async def confirm_signup(token_hash: str, type: str = "signup") -> AuthTokens:
    """Exchange an email confirmation token for a session."""
    supabase = await get_user_supabase()
    res = await supabase.auth.verify_otp(
        VerifyTokenHashParams(token_hash=token_hash, type=cast(EmailOtpType, type))
    )
    if res.session is None:
        raise ValueError("Email confirmation failed: no session returned")
    return AuthTokens(
        access_token=res.session.access_token,
        refresh_token=res.session.refresh_token,
    )
