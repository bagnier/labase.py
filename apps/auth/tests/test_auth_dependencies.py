import uuid
from unittest.mock import MagicMock, patch

import jwt
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from supabase_auth.errors import AuthApiError

from apps.auth.contract.user import AuthenticatedUser
from apps.auth.domain.service import AuthTokens, login
from apps.auth.infra.security import get_current_user

_app = FastAPI()


@_app.get("/me")
async def me(user=Depends(get_current_user)):
    return {"id": str(user.id)}


@pytest_asyncio.fixture()
async def client():
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        yield c


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
    # A well-formed JWT structure but signed with a different key
    client.cookies.set(
        "access_token",
        "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiIxMjMiLCJhdWQiOiJhdXRoZW50aWNhdGVkIn0"
        ".AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    )
    response = await client.get("/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_valid_token_returns_user(client, test_user):
    email, password = test_user
    tokens = await login(email, password)
    client.cookies.set("access_token", tokens.access_token)
    response = await client.get("/me")
    assert response.status_code == 200
    assert response.json()["id"]


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
    # A mid-window refresh must re-emit the session capped to the impersonation window's
    # remaining time, not the long login TTL — otherwise the disguise outlives its time-box.
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
    # Past the deadline the target session must die with the banner, not silently refresh.
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
    refresh.assert_not_called()  # refused before spending a refresh round-trip


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
async def test_expired_token_stale_refresh_logs_info_not_exception(client):
    # A 4xx AuthApiError is GoTrue's routine "your refresh token is bad" — the end of a
    # session, not a bug. It logs at info; log.exception (the capture seam) must not fire.
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
    log.info.assert_called_once()
    log.exception.assert_not_called()


@pytest.mark.asyncio
async def test_expired_token_unexpected_refresh_failure_logs_exception(client):
    # GoTrue unreachable / 5xx / a bug is not a routine "no" — log.exception is the capture seam.
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
    log.exception.assert_called_once_with("auth.token_refresh_failed")
    log.info.assert_not_called()


def test_log_gotrue_failure_picks_level_by_nature():
    from apps.auth.infra.router import _log_gotrue_failure

    with patch("apps.auth.infra.router.log") as log:  # 4xx AuthApiError = normal user outcome
        _log_gotrue_failure("auth.x", AuthApiError("bad link", 400, None))
        log.info.assert_called_once()
        log.exception.assert_not_called()

    with patch("apps.auth.infra.router.log") as log:  # 5xx AuthApiError = a bug → captured
        _log_gotrue_failure("auth.x", AuthApiError("gotrue down", 500, None))
        log.exception.assert_called_once()
        log.info.assert_not_called()

    with patch("apps.auth.infra.router.log") as log:  # any other error = a bug → captured
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


def test_register_unexpected_exception_returns_400(driver):
    creds = {"email": "x@test.local", "password": "pw"}
    with patch("apps.auth.infra.router.register_user", side_effect=RuntimeError("unexpected")):
        response = driver.client().post("/auth/register", data=creds)
    assert response.status_code == 400
    assert "unexpected error" in response.text.lower()


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

    # No clear on teardown: the context is transaction-local, discarded by the request's
    # single commit/rollback — so get_rls_session never issues reset round-trips.
    with patch("apps.auth.infra.session.set_rls_context", side_effect=mock_set):
        gen = get_rls_session(current_user=fake_user, session=fake_session)
        session = await gen.__anext__()
        assert session is fake_session
        assert set_calls, "set_rls_context should have been called"
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()


@pytest.mark.asyncio
async def test_get_rls_session_skips_context_for_anonymous_caller():
    from apps.auth.infra.session import get_rls_session

    fake_session = MagicMock()
    set_calls = []

    async def mock_set(session, uid):
        set_calls.append(uid)

    with patch("apps.auth.infra.session.set_rls_context", side_effect=mock_set):
        gen = get_rls_session(current_user=None, session=fake_session)
        session = await gen.__anext__()
        assert session is fake_session
        assert not set_calls, "anonymous caller must not set an RLS context"
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()
