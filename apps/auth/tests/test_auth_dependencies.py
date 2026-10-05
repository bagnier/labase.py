import uuid
from contextlib import asynccontextmanager
from unittest.mock import ANY, MagicMock, patch

import jwt
import pytest
import pytest_asyncio
import structlog
from fastapi import Depends, FastAPI
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_dependant
from httpx import ASGITransport, AsyncClient
from supabase_auth.errors import AuthApiError

from apps.auth.contract.api_keys import API_KEY_PREFIX, ApiKeyQuery
from apps.auth.contract.user import AuthenticatedUser
from apps.auth.domain.service import AuthTokens, PasswordUpdateError, login
from apps.auth.infra.security import get_current_user
from apps.auth.infra.security import log as security_log
from apps.shared.integration.contribs import Contribs
from apps.shared.logs import capture
from apps.shared.persistence import database as db
from apps.shared.persistence.database import get_admin_session

_app = FastAPI()


@_app.get("/me")
async def me(user=Depends(get_current_user)):
    return {"id": str(user.id)}


def _clear_engine_caches() -> None:
    db._user_engine.cache_clear()
    db._user_session_factory.cache_clear()
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest_asyncio.fixture()
async def client():
    # Resolving a user may read the factor table: the cached engines must bind to this loop.
    _clear_engine_caches()
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        yield c
    await db._user_engine().dispose()
    await db._admin_engine().dispose()
    _clear_engine_caches()


@pytest.mark.asyncio
async def test_no_cookie_returns_401(client):
    response = await client.get("/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_returns_401(client):
    client.cookies.set("access_token", "garbage")
    response = await client.get("/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_wrong_signature_returns_401(client):
    # Well-formed, signed with another key
    client.cookies.set(
        "access_token",
        "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiIxMjMiLCJhdWQiOiJhdXRoZW50aWNhdGVkIn0"
        ".AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    )
    response = await client.get("/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_api_key_bearer_returns_401_when_no_provider_matches(client):
    with patch("apps.auth.infra.security.contribs", Contribs()):
        response = await client.get(
            "/me", headers={"Authorization": f"Bearer {API_KEY_PREFIX}whatever"}
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_api_key_bearer_returns_503_when_the_provider_fails(client):
    """Not a 401: the key may well be valid."""
    fresh = Contribs()

    async def boom(query: ApiKeyQuery) -> None:
        raise RuntimeError("provider broke")

    fresh.provide(ApiKeyQuery, boom)

    with patch("apps.auth.infra.security.contribs", fresh):
        response = await client.get(
            "/me", headers={"Authorization": f"Bearer {API_KEY_PREFIX}whatever"}
        )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_valid_token_returns_user(client, test_user):
    email, password = test_user
    tokens = await login(email, password)
    client.cookies.set("access_token", tokens.access_token)
    response = await client.get("/me")
    assert response.status_code == 200
    assert response.json()["id"]


@pytest.mark.asyncio
async def test_api_key_auth_lets_a_captured_issue_keep_its_user():
    """Capture keeps only scalar context, so ``user_id`` must be bound as a string."""
    user_id = uuid.UUID("00000000-0000-0000-0000-000000000042")
    principal = AuthenticatedUser(id=user_id, email="key@test.local")

    @asynccontextmanager
    async def _no_identity_yet(session):
        yield

    capture._QUEUE.clear()
    structlog.contextvars.clear_contextvars()
    with (
        patch("apps.auth.infra.security._resolve_api_key", return_value=principal),
        patch("apps.auth.infra.security._before_identity", _no_identity_yet),
    ):
        await get_current_user(
            response=MagicMock(),
            authorization=f"Bearer {API_KEY_PREFIX}abc123",
            session=MagicMock(),
        )
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            security_log.exception("auth.probe_captured", exc_info=exc)

    assert capture._QUEUE[-1].context == {
        "event": "auth.probe_captured",
        "logger": "apps.auth.infra.security",
        "user_id": str(user_id),
    }


@pytest.mark.asyncio
async def test_expired_token_with_valid_refresh_returns_200_and_sets_new_cookies(client, test_user):
    email, password = test_user
    real_tokens = await login(email, password)
    fake_new_tokens = AuthTokens(
        access_token=real_tokens.access_token, refresh_token=real_tokens.refresh_token
    )

    client.cookies.set("access_token", "expired.token.value")
    client.cookies.set("refresh_token", real_tokens.refresh_token)

    with (
        patch(
            "apps.auth.infra.security.decode_jwt",
            side_effect=[
                jwt.ExpiredSignatureError,
                {"sub": "00000000-0000-0000-0000-000000000009", "email": email},
            ],
        ),
        patch("apps.auth.infra.security.refresh_session", return_value=fake_new_tokens),
    ):
        response = await client.get("/me")

    assert response.status_code == 200
    assert response.json()["id"] == "00000000-0000-0000-0000-000000000009"
    assert "access_token" in response.cookies
    assert "refresh_token" in response.cookies


def _access_cookie_max_age(response) -> int:
    for header in response.headers.get_list("set-cookie"):
        if header.startswith("access_token="):
            for part in header.split(";"):
                key, _, value = part.strip().partition("=")
                if key.lower() == "max-age":
                    return int(value)
    raise AssertionError("no access_token Set-Cookie with Max-Age")


def test_impersonation_remaining_reads_deadline():
    import time

    from apps.auth.infra.security import _impersonation_remaining

    assert _impersonation_remaining(None) is None
    assert _impersonation_remaining("") is None
    assert _impersonation_remaining("not-a-number") is None
    future = _impersonation_remaining(str(int(time.time()) + 100))
    assert future is not None
    assert future > 0
    past = _impersonation_remaining(str(int(time.time()) - 100))
    assert past is not None
    assert past < 0


@pytest.mark.asyncio
async def test_refresh_while_impersonating_caps_cookie_to_window(client, test_user):
    import time

    email, password = test_user
    real_tokens = await login(email, password)
    fake_new_tokens = AuthTokens(
        access_token=real_tokens.access_token, refresh_token=real_tokens.refresh_token
    )
    client.cookies.set("access_token", "expired.token.value")
    client.cookies.set("refresh_token", real_tokens.refresh_token)
    client.cookies.set("impersonator_deadline", str(int(time.time()) + 120))

    with (
        patch(
            "apps.auth.infra.security.decode_jwt",
            side_effect=[
                jwt.ExpiredSignatureError,
                {"sub": "00000000-0000-0000-0000-000000000009", "email": email},
            ],
        ),
        patch("apps.auth.infra.security.refresh_session", return_value=fake_new_tokens),
    ):
        response = await client.get("/me")

    assert response.status_code == 200
    assert _access_cookie_max_age(response) <= 120


@pytest.mark.asyncio
async def test_refresh_after_impersonation_window_returns_401(client, test_user):
    import time

    email, password = test_user
    real_tokens = await login(email, password)
    client.cookies.set("access_token", "expired.token.value")
    client.cookies.set("refresh_token", real_tokens.refresh_token)
    client.cookies.set("impersonator_deadline", str(int(time.time()) - 1))

    with (
        patch("apps.auth.infra.security.decode_jwt", side_effect=jwt.ExpiredSignatureError),
        patch("apps.auth.infra.security.refresh_session") as refresh,
    ):
        response = await client.get("/me")

    assert response.status_code == 401
    refresh.assert_not_called()


@pytest.mark.asyncio
async def test_expired_token_without_refresh_returns_401(client):
    client.cookies.set("access_token", "expired.token.value")

    with patch("apps.auth.infra.security.decode_jwt", side_effect=jwt.ExpiredSignatureError):
        response = await client.get("/me")

    assert response.status_code == 401


def test_profile_browser_redirect_to_login_when_unauthenticated(driver):
    response = driver.client().get(
        "/profile",
        headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login?next=/profile"


def test_profile_api_client_gets_401_with_json_accept(driver):
    response = driver.client().get(
        "/profile",
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_with_invalid_refresh_returns_401(client):
    client.cookies.set("access_token", "expired.token.value")
    client.cookies.set("refresh_token", "invalid.refresh.token")

    with (
        patch("apps.auth.infra.security.decode_jwt", side_effect=jwt.ExpiredSignatureError),
        patch("apps.auth.infra.security.refresh_session", side_effect=ValueError("Refresh failed")),
    ):
        response = await client.get("/me")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_stale_refresh_logs_nothing(client):
    """The everyday end of a session."""
    stale = AuthApiError("Invalid Refresh Token: Refresh Token Not Found", 400, None)
    client.cookies.set("access_token", "expired.token.value")
    client.cookies.set("refresh_token", "stale.refresh.token")

    with (
        patch("apps.auth.infra.security.decode_jwt", side_effect=jwt.ExpiredSignatureError),
        patch("apps.auth.infra.security.refresh_session", side_effect=stale),
        patch("apps.auth.infra.security.log") as log,
    ):
        response = await client.get("/me")

    assert response.status_code == 401
    assert log.mock_calls == []


@pytest.mark.asyncio
async def test_expired_token_refresh_rate_limited_logs_info(client):
    """A 429 can sign out every user at once."""
    limited = AuthApiError("Request rate limit reached", 429, "over_request_rate_limit")
    client.cookies.set("access_token", "expired.token.value")
    client.cookies.set("refresh_token", "some.refresh.token")

    with (
        patch("apps.auth.infra.security.decode_jwt", side_effect=jwt.ExpiredSignatureError),
        patch("apps.auth.infra.security.refresh_session", side_effect=limited),
        patch("apps.auth.infra.security.log") as log,
    ):
        response = await client.get("/me")

    assert response.status_code == 401
    log.info.assert_called_once()
    log.exception.assert_not_called()


@pytest.mark.asyncio
async def test_expired_token_unexpected_refresh_failure_logs_exception(client):
    boom = RuntimeError("gotrue unreachable")
    client.cookies.set("access_token", "expired.token.value")
    client.cookies.set("refresh_token", "some.refresh.token")

    with (
        patch("apps.auth.infra.security.decode_jwt", side_effect=jwt.ExpiredSignatureError),
        patch("apps.auth.infra.security.refresh_session", side_effect=boom),
        patch("apps.auth.infra.security.log") as log,
    ):
        response = await client.get("/me")

    assert response.status_code == 401
    log.exception.assert_called_once_with(
        "auth.token_refresh_failed", exc_info=boom, detail=str(boom)
    )
    log.info.assert_not_called()


def test_auth_takes_its_level_from_the_bases_verdict():
    """The verdict itself is tested in ``apps/shared``; this holds that auth uses it."""
    from apps.auth.infra.router import _log_gotrue_failure

    with patch("apps.auth.infra.router.log") as log:  # 4xx: a refusal
        _log_gotrue_failure("auth.x", AuthApiError("bad link", 400, None))
        log.info.assert_called_once()
        log.exception.assert_not_called()

    with patch("apps.auth.infra.router.log") as log:  # unreachable: an issue
        _log_gotrue_failure("auth.x", RuntimeError("boom"))
        log.exception.assert_called_once()
        log.info.assert_not_called()


def test_login_unexpected_exception_returns_503(driver):
    creds = {"email": "x@test.local", "password": "pw"}
    with patch("apps.auth.infra.router.login", side_effect=RuntimeError("unexpected")):
        response = driver.client().post("/auth/login", data=creds)
    assert response.status_code == 503
    assert "system error" in response.text.lower()


def test_login_email_not_confirmed_returns_401_with_message(driver):
    err = AuthApiError("Email not confirmed", 400, "email_not_confirmed")
    creds = {"email": "x@test.local", "password": "pw"}
    with patch("apps.auth.infra.router.login", side_effect=err):
        response = driver.client().post("/auth/login", data=creds)
    assert response.status_code == 401
    assert "verify your email" in response.text.lower()


def test_login_wrong_password_returns_401_with_generic_message(driver):
    err = AuthApiError("Invalid login credentials", 400, "invalid_credentials")
    creds = {"email": "x@test.local", "password": "pw"}
    with patch("apps.auth.infra.router.login", side_effect=err):
        response = driver.client().post("/auth/login", data=creds)
    assert response.status_code == 401
    assert "invalid email or password" in response.text.lower()


def test_password_reset_gotrue_outage_is_logged_not_silent(driver):
    """Not swallowed by the "recovery token already consumed" branch."""
    outage = PasswordUpdateError("Service Unavailable", 503)
    tokens = AuthTokens(
        access_token="recovery.access.token", refresh_token="recovery.refresh.token"
    )
    with (
        patch("apps.auth.infra.router.confirm_signup", return_value=tokens),
        patch("apps.auth.infra.router.update_password", side_effect=outage),
        patch("apps.auth.infra.router.log") as log,
    ):
        response = driver.client().post(
            "/auth/reset-password", data={"token_hash": "abc", "password": "NewPass1!"}
        )
    assert response.status_code == 400
    log.exception.assert_called_once_with("auth.password_reset_failed", exc_info=outage, ip=ANY)


def test_password_reset_consumed_token_returns_400_without_opening_an_issue(driver):
    """It keeps its own message and opens no issue."""
    refused = PasswordUpdateError("Token has expired or is invalid", 401)
    tokens = AuthTokens(
        access_token="recovery.access.token", refresh_token="recovery.refresh.token"
    )
    with (
        patch("apps.auth.infra.router.confirm_signup", return_value=tokens),
        patch("apps.auth.infra.router.update_password", side_effect=refused),
        patch("apps.auth.infra.router.log") as log,
    ):
        response = driver.client().post(
            "/auth/reset-password", data={"token_hash": "abc", "password": "NewPass1!"}
        )
    assert response.status_code == 400
    assert "please request a new reset link" in response.text.lower()
    log.exception.assert_not_called()


def test_register_unexpected_exception_returns_400(driver):
    creds = {"email": "x@test.local", "password": "pw"}
    with patch("apps.auth.infra.router.register_user", side_effect=RuntimeError("unexpected")):
        response = driver.client().post("/auth/register", data=creds)
    assert response.status_code == 400
    assert "unexpected error" in response.text.lower()


def test_login_gotrue_5xx_is_captured_as_an_issue_not_a_refusal(driver):
    # A 500 with a JSON body is a breakage like any 5xx: an issue and the system-error answer,
    # never "invalid password".
    creds = {"email": "x@test.local", "password": "pw"}
    err = AuthApiError("Internal Server Error", 500, None)
    with (
        patch("apps.auth.infra.router.login", side_effect=err),
        patch("apps.auth.infra.router.log") as log,
    ):
        response = driver.client().post("/auth/login", data=creds)
    assert response.status_code == 503
    assert "system error" in response.text.lower()
    log.warning.assert_not_called()
    log.exception.assert_called_once()


def test_register_gotrue_5xx_is_captured_as_an_issue_not_a_refusal(driver):
    # Likewise: "unexpected error", never GoTrue's raw message.
    creds = {"email": "x@test.local", "password": "pw"}
    err = AuthApiError("Internal Server Error", 500, None)
    with (
        patch("apps.auth.infra.router.register_user", side_effect=err),
        patch("apps.auth.infra.router.log") as log,
    ):
        response = driver.client().post("/auth/register", data=creds)
    assert response.status_code == 400
    assert "unexpected error" in response.text.lower()
    log.warning.assert_not_called()
    log.exception.assert_called_once()


def test_login_refusal_still_warns_instead_of_opening_an_issue(driver):
    # A wrong password still gets the brute-force warning, not an issue.
    creds = {"email": "x@test.local", "password": "pw"}
    err = AuthApiError("Invalid login credentials", 400, "invalid_credentials")
    with (
        patch("apps.auth.infra.router.login", side_effect=err),
        patch("apps.auth.infra.router.log") as log,
    ):
        response = driver.client().post("/auth/login", data=creds)
    assert response.status_code == 401
    log.exception.assert_not_called()
    log.warning.assert_called_once_with("auth.login_failed", email="x@test.local", ip="127.0.0.1")


def test_register_refusal_still_warns_instead_of_opening_an_issue(driver):
    creds = {"email": "x@test.local", "password": "pw"}
    err = AuthApiError("User already registered", 400, "user_already_exists")
    with (
        patch("apps.auth.infra.router.register_user", side_effect=err),
        patch("apps.auth.infra.router.log") as log,
    ):
        response = driver.client().post("/auth/register", data=creds)
    assert response.status_code == 400
    log.exception.assert_not_called()
    log.warning.assert_called_once_with(
        "auth.register_failed", ip="127.0.0.1", email="x@test.local", code="user_already_exists"
    )


@pytest.mark.asyncio
async def test_get_rls_session_sets_context_and_relies_on_commit_to_clear():
    from apps.auth.infra.session import get_rls_session

    fake_user = AuthenticatedUser(
        id=uuid.UUID("00000000-0000-0000-0000-000000000001"), email="t@test.local"
    )
    fake_session = MagicMock()

    set_calls = []

    async def mock_set(session, uid):
        set_calls.append(uid)

    # No reset on teardown: the context is transaction-local.
    with patch("apps.auth.infra.session.set_rls_context", side_effect=mock_set):
        gen = get_rls_session(current_user=fake_user, session=fake_session)
        session = await gen.__anext__()
        assert session is fake_session
        assert set_calls, "set_rls_context should have been called"
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()


@pytest.mark.asyncio
async def test_get_rls_session_gives_an_anonymous_caller_a_context_with_no_identity():
    """On the bare login role an anonymous query is denied."""
    from apps.auth.infra.session import get_rls_session

    fake_session = MagicMock()
    set_calls = []

    async def mock_set(session, claims):
        set_calls.append(claims)

    with patch("apps.auth.infra.session.set_rls_context", side_effect=mock_set):
        gen = get_rls_session(current_user=None, session=fake_session)
        await gen.__anext__()

    assert set_calls == [{"role": "anon"}]


def _calls(dependant: Dependant) -> set:
    return {call for child in dependant.dependencies for call in {child.call} | _calls(child)}


def test_knowing_who_asks_opens_no_bypassrls_session():
    """(AGENTS: three sessions, and RLS by default)"""
    calls = _calls(get_dependant(path="/", call=get_current_user))

    assert get_admin_session not in calls
