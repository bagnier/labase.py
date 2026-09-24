"""`grant_admin` / `set_admin` read the GoTrue directory once — the lookup, the last-admin
guard and the returned list all come from that one scan, not a fresh one each.

GoTrue is a service we own the boundary of, not our own domain code — stubbed the way
`test_admin_bootstrap.py` stubs it, never with `AsyncMock`/`MagicMock` standing in for our
own functions."""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.console.domain import admins


def _user(
    user_id: uuid.UUID, email: str, *, role: str | None = None, banned: bool = False
) -> SimpleNamespace:
    return SimpleNamespace(
        id=str(user_id),
        email=email,
        app_metadata={"role": role} if role else {},
        deleted_at=None,
        banned_until="2126-01-01T00:00:00Z" if banned else None,
    )


def _gotrue(users: list[SimpleNamespace]) -> tuple[MagicMock, list[str]]:
    """A stubbed GoTrue admin API: the accounts it lists, and a record of every ``list_users``
    call — the observable count a directory scan costs."""
    calls: list[str] = []
    client = MagicMock()

    def list_users(**_: object) -> list[SimpleNamespace]:
        calls.append("list_users")
        return users

    client.auth.admin.list_users = list_users
    client.auth.admin.update_user_by_id = lambda uid, attrs: None
    return client, calls


@pytest.mark.asyncio
async def test_granting_an_admin_scans_the_directory_once():
    target = uuid.uuid7()
    client, calls = _gotrue([_user(target, "bob@test.local")])

    with patch("apps.auth.infra.user_repository.get_admin_supabase", return_value=client):
        await admins.grant_admin("bob@test.local")

    assert calls == ["list_users"]


@pytest.mark.asyncio
async def test_setting_admin_status_scans_the_directory_once():
    target = uuid.uuid7()
    client, calls = _gotrue(
        [_user(target, "bob@test.local"), _user(uuid.uuid7(), "root@test.local", role="admin")]
    )

    with patch("apps.auth.infra.user_repository.get_admin_supabase", return_value=client):
        await admins.set_admin("bob@test.local", is_admin=True)

    assert calls == ["list_users"]


@pytest.mark.asyncio
async def test_revoking_the_last_unbanned_admin_is_blocked_by_a_banned_peer():
    """Issue #79: a banned admin has an admin's role but cannot sign in — it must not count as
    the safety net that lets the server's last acting admin give up their role."""
    active = uuid.uuid7()
    client, _ = _gotrue(
        [
            _user(active, "root@test.local", role="admin"),
            _user(uuid.uuid7(), "bob@test.local", role="admin", banned=True),
        ]
    )

    with (
        patch("apps.auth.infra.user_repository.get_admin_supabase", return_value=client),
        pytest.raises(admins.LastAdminViolation),
    ):
        await admins.set_admin("root@test.local", is_admin=False)
