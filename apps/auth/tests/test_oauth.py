"""OAuth domain service: PKCE pair, authorize URL, code-for-session exchange."""

import base64
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest

from apps.auth.domain.service import (
    OAuthError,
    exchange_oauth_code,
    oauth_authorize_url,
    pkce_pair,
)


def test_pkce_pair_challenge_is_the_s256_of_the_verifier():
    verifier, challenge = pkce_pair()
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    assert challenge == expected
    assert 43 <= len(verifier) <= 128  # RFC 7636 bounds


def test_pkce_pair_is_fresh_every_time():
    assert pkce_pair()[0] != pkce_pair()[0]


def test_oauth_authorize_url_targets_gotrue_with_the_challenge():
    url = oauth_authorize_url("github", "http://app.local/auth/callback", "chall")
    parts = urlsplit(url)
    assert parts.path.endswith("/auth/v1/authorize")
    query = parse_qs(parts.query)
    assert query["provider"] == ["github"]
    assert query["redirect_to"] == ["http://app.local/auth/callback"]
    assert query["code_challenge"] == ["chall"]
    assert query["code_challenge_method"] == ["s256"]


def _client_returning(response) -> MagicMock:
    client_cls = MagicMock()
    client = AsyncMock()
    client.post = AsyncMock(return_value=response)
    client_cls.return_value.__aenter__ = AsyncMock(return_value=client)
    client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return client_cls


@pytest.mark.asyncio
async def test_exchange_oauth_code_returns_tokens():
    response = MagicMock(status_code=200)
    response.json.return_value = {"access_token": "at", "refresh_token": "rt"}
    client_cls = _client_returning(response)
    with patch("apps.auth.domain.service.httpx.AsyncClient", client_cls):
        tokens = await exchange_oauth_code("the-code", "the-verifier")
    assert (tokens.access_token, tokens.refresh_token) == ("at", "rt")
    call = client_cls.return_value.__aenter__.return_value.post.call_args
    assert "grant_type=pkce" in call.args[0]
    assert call.kwargs["json"] == {"auth_code": "the-code", "code_verifier": "the-verifier"}


@pytest.mark.asyncio
async def test_exchange_oauth_code_raises_user_safe_error():
    response = MagicMock(status_code=400)
    response.json.return_value = {"error_description": "Code challenge mismatch"}
    with (
        patch("apps.auth.domain.service.httpx.AsyncClient", _client_returning(response)),
        pytest.raises(OAuthError, match="Code challenge mismatch"),
    ):
        await exchange_oauth_code("bad", "bad")
