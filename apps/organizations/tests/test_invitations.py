"""Tests for invitation_router.py branches not covered by BDD scenarios."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from apps.auth.contract.current import AuthenticatedUser, get_current_user
from apps.main import host
from apps.shared.clock import now
from apps.shared.persistence.database import get_admin_session, get_user_session

app = host.app


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=True)


def _mock_admin_session(row=None):
    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = row
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def _override():
        yield mock_session

    return _override


def _mock_rls_session():
    mock_session = AsyncMock()

    async def _override():
        yield mock_session

    return _override


def _mock_user(user_id: uuid.UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")):
    async def _override():
        return AuthenticatedUser(id=user_id, email="test@test.local")

    return _override


# ── GET /invitations/{token} ──────────────────────────────────────────────────


def test_get_invitation_unknown_token_html_returns_invalid_state(client):
    token = uuid.uuid4()
    app.dependency_overrides[get_admin_session] = _mock_admin_session(row=None)
    try:
        resp = client.get(f"/invitations/{token}", headers={"accept": "text/html"})
        assert resp.status_code == 404
        assert "invalid" in resp.text.lower()
    finally:
        app.dependency_overrides.pop(get_admin_session, None)


def test_get_invitation_unknown_token_json_returns_404(client):
    token = uuid.uuid4()
    app.dependency_overrides[get_admin_session] = _mock_admin_session(row=None)
    try:
        resp = client.get(f"/invitations/{token}", headers={"accept": "application/json"})
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_admin_session, None)


def test_get_invitation_revoked_json_returns_404(client):
    token = uuid.uuid4()
    fake_row = {
        "id": uuid.uuid7(),
        "org_id": uuid.uuid7(),
        "email": "x@test.local",
        "role": "member",
        "token": token,
        "status": "revoked",
        "created_at": None,
    }
    app.dependency_overrides[get_admin_session] = _mock_admin_session(row=fake_row)
    try:
        resp = client.get(f"/invitations/{token}", headers={"accept": "application/json"})
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()
    finally:
        app.dependency_overrides.pop(get_admin_session, None)


def test_get_invitation_valid_json_returns_invitation(client):
    token = uuid.uuid4()
    org_id = uuid.uuid7()
    fake_row = {
        "id": uuid.uuid7(),
        "org_id": org_id,
        "email": "x@test.local",
        "role": "member",
        "token": token,
        "status": "pending",
        "created_at": now(),
    }
    app.dependency_overrides[get_admin_session] = _mock_admin_session(row=fake_row)
    try:
        resp = client.get(f"/invitations/{token}", headers={"accept": "application/json"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["email"] == "x@test.local"
    finally:
        app.dependency_overrides.pop(get_admin_session, None)


def test_get_invitation_already_accepted_html_shows_state(client):
    token = uuid.uuid4()
    org_id = uuid.uuid7()
    fake_row = {
        "id": uuid.uuid7(),
        "org_id": org_id,
        "email": "x@test.local",
        "role": "member",
        "token": token,
        "status": "accepted",
        "created_at": None,
    }
    mock_org = MagicMock()
    mock_org.name = "Test Org"

    mock_result = MagicMock()
    mock_result.mappings.return_value.first.return_value = fake_row
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    async def _override():
        yield mock_session

    with patch(
        "apps.organizations.infra.invitation_router.OrganizationRepository.get",
        AsyncMock(return_value=mock_org),
    ):
        app.dependency_overrides[get_admin_session] = _override
        try:
            resp = client.get(f"/invitations/{token}", headers={"accept": "text/html"})
            assert resp.status_code == 200
            assert "already_accepted" in resp.text or "accepted" in resp.text.lower()
        finally:
            app.dependency_overrides.pop(get_admin_session, None)


# ── POST /invitations/{token}/accept ─────────────────────────────────────────


def test_accept_already_accepted_invitation_is_idempotent(client):
    token = uuid.uuid4()
    org_id = uuid.uuid7()
    fake_row = {
        "id": uuid.uuid7(),
        "org_id": org_id,
        "email": "test@test.local",
        "role": "member",
        "token": token,
        "status": "accepted",
        "created_at": None,
    }
    mock_org = MagicMock()
    mock_org.handle = "test-org"

    app.dependency_overrides[get_admin_session] = _mock_admin_session(row=fake_row)
    app.dependency_overrides[get_user_session] = _mock_rls_session()
    app.dependency_overrides[get_current_user] = _mock_user()
    try:
        with patch(
            "apps.organizations.infra.invitation_router.OrganizationRepository.get",
            AsyncMock(return_value=mock_org),
        ):
            resp = client.post(
                f"/invitations/{token}/accept",
                headers={"accept": "application/json"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "redirect" in data
        assert "/dashboard" in data["redirect"]
    finally:
        app.dependency_overrides.pop(get_admin_session, None)
        app.dependency_overrides.pop(get_user_session, None)
        app.dependency_overrides.pop(get_current_user, None)


def test_accept_non_pending_invitation_returns_404(client):
    token = uuid.uuid4()
    fake_row = {
        "id": uuid.uuid7(),
        "org_id": uuid.uuid7(),
        "email": "t@test.local",
        "role": "member",
        "token": token,
        "status": "revoked",
        "created_at": None,
    }
    app.dependency_overrides[get_admin_session] = _mock_admin_session(row=fake_row)
    app.dependency_overrides[get_user_session] = _mock_rls_session()
    app.dependency_overrides[get_current_user] = _mock_user()
    try:
        resp = client.post(
            f"/invitations/{token}/accept",
            headers={"accept": "application/json"},
        )
        assert resp.status_code == 404
    finally:
        app.dependency_overrides.pop(get_admin_session, None)
        app.dependency_overrides.pop(get_user_session, None)
        app.dependency_overrides.pop(get_current_user, None)
