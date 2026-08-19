import base64
import hashlib
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from urllib.parse import urlencode

import httpx
import structlog
from supabase_auth.types import EmailOtpType, VerifyTokenHashParams

from apps.shared.config import get_technical_settings
from apps.shared.persistence.supabase import get_user_supabase

log = structlog.get_logger(__name__)


def _auth_headers(access_token: str) -> dict[str, str]:
    """Bearer + apikey headers for a stateless authenticated GoTrue call."""
    s = get_technical_settings()
    return {"Authorization": f"Bearer {access_token}", "apikey": s.supabase_publishable_key}


def _error_message(res: httpx.Response, fallback: str) -> str:
    """The GoTrue error ``msg`` from a failed response, or ``fallback`` when the body is absent
    or not JSON — the user-safe message extraction shared by the stateless GoTrue calls."""
    try:
        return res.json().get("msg", fallback)
    except ValueError:
        return fallback


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
                headers=_auth_headers(access_token),
            )
    except Exception as exc:
        log.warning("auth.signout_failed", exc_info=exc)


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


def _parse_ts(value: str) -> datetime:
    """Parse a GoTrue timestamp, tolerating nanosecond precision (9 digits) and a trailing ``Z`` —
    ``datetime`` only handles microseconds (6 digits) and a numeric offset."""
    value = re.sub(r"(\.\d{6})\d+", r"\1", value).replace("Z", "+00:00")
    return datetime.fromisoformat(value)


def _is_first_sign_in(user: dict) -> bool:
    """Whether a GoTrue user object is at its very first sign-in, so the OAuth callback provisions
    the account (``UserCreated``) once and never on a returning login. GoTrue stamps ``created_at``
    and ``last_sign_in_at`` in the same sign-up (milliseconds apart); a returning user's last
    sign-in is far later. A user with no recorded sign-in yet also counts as new."""
    created = user.get("created_at")
    last = user.get("last_sign_in_at")
    if not created:
        return False  # nothing to key on — don't provision
    if not last:
        return True  # exists but never signed in → this is the first
    return abs(_parse_ts(last) - _parse_ts(created)) < timedelta(seconds=5)


async def exchange_oauth_code(code: str, code_verifier: str) -> tuple[AuthTokens, bool]:
    """PKCE code-for-session exchange — stateless, like every GoTrue call here. Returns the tokens
    and whether this is the user's first sign-in (so the callback provisions the account once)."""
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
    tokens = AuthTokens(access_token=data["access_token"], refresh_token=data["refresh_token"])
    return tokens, _is_first_sign_in(data.get("user") or {})


class PasskeyError(Exception):
    """GoTrue refused the passkey operation; message is user-safe."""


async def _passkey_request(
    method: str, path: str, json: dict | None = None, access_token: str | None = None
) -> Any:
    """Stateless GoTrue passkeys call (beta API, no supabase-py support yet)."""
    s = get_technical_settings()
    headers = {"apikey": s.supabase_publishable_key}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    async with httpx.AsyncClient() as client:
        res = await client.request(
            method, f"{s.supabase_api_url}/auth/v1/passkeys{path}", headers=headers, json=json
        )
    if res.status_code >= 400:
        raise PasskeyError(_error_message(res, "Passkey operation failed."))
    return res.json() if res.content else None


async def passkey_registration_options(access_token: str) -> dict[str, Any]:
    """WebAuthn creation options for the signed-in user — {challenge_id, options, …}."""
    return await _passkey_request("POST", "/registration/options", {}, access_token)


async def verify_passkey_registration(
    access_token: str, challenge_id: str, credential: dict[str, Any]
) -> dict[str, Any]:
    return await _passkey_request(
        "POST",
        "/registration/verify",
        {"challenge_id": challenge_id, "credential": credential},
        access_token,
    )


async def list_passkeys(access_token: str) -> list[dict[str, Any]]:
    return await _passkey_request("GET", "/", access_token=access_token) or []


async def delete_passkey(access_token: str, passkey_id: str) -> None:
    await _passkey_request("DELETE", f"/{passkey_id}", access_token=access_token)


async def passkey_authentication_options() -> dict[str, Any]:
    """Anonymous discoverable-credential request options — {challenge_id, options, …}."""
    return await _passkey_request("POST", "/authentication/options", {})


async def verify_passkey_authentication(
    challenge_id: str, credential: dict[str, Any]
) -> AuthTokens:
    data = await _passkey_request(
        "POST",
        "/authentication/verify",
        {"challenge_id": challenge_id, "credential": credential},
    )
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
            headers=_auth_headers(access_token),
            json=json,
        )
    if res.status_code >= 400:
        raise TotpError(_error_message(res, "Two-factor operation failed."))
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
            headers=_auth_headers(access_token),
        )
    if res.status_code >= 400:
        return None
    for factor in res.json().get("factors") or []:
        if factor.get("factor_type") == "totp" and factor.get("status") == "verified":
            return str(factor.get("id"))
    return None


class PasswordUpdateError(Exception):
    """GoTrue refused the new password (typically weak_password); message is user-safe."""


async def _update_user(
    access_token: str, payload: dict, error_type: type[Exception], fallback: str
) -> None:
    """PUT to GoTrue's ``/auth/v1/user`` (password or email change) — stateless, like logout();
    on a 4xx/5xx raise ``error_type`` carrying the user-safe GoTrue message."""
    s = get_technical_settings()
    async with httpx.AsyncClient() as client:
        res = await client.put(
            f"{s.supabase_api_url}/auth/v1/user",
            headers=_auth_headers(access_token),
            json=payload,
        )
    if res.status_code >= 400:
        raise error_type(_error_message(res, fallback))


async def update_password(access_token: str, new_password: str) -> None:
    """Set a new password for the session's user."""
    await _update_user(
        access_token, {"password": new_password}, PasswordUpdateError, "Password update failed."
    )


class EmailChangeError(Exception):
    """GoTrue refused the email change (invalid or taken address); message is user-safe."""


async def request_email_change(access_token: str, new_email: str) -> None:
    """Ask GoTrue to mail a confirmation to the new address."""
    await _update_user(access_token, {"email": new_email}, EmailChangeError, "Email change failed.")


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
