"""The first-admin bootstrap. Delivered later, the fact may name a deleted account: only one the
admin count sees may be promoted, or every next signup is.
"""

import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.contract.events import UserCreated
from apps.console.contract.integration import _bootstrap_first_admin

_NO_SESSION = cast(AsyncSession, None)  # the handler uses the GoTrue admin API


def _user(
    user_id: uuid.UUID, *, role: str | None = None, deleted: bool = False, banned: bool = False
) -> SimpleNamespace:
    return SimpleNamespace(
        id=str(user_id),
        email=f"{user_id}@example.com",
        app_metadata={"role": role} if role else {},
        deleted_at="2026-08-20T00:00:00Z" if deleted else None,
        banned_until="2126-08-20T00:00:00Z" if banned else None,
    )


def _gotrue(users: list[SimpleNamespace]) -> tuple[MagicMock, list[tuple[str, dict]]]:
    """The accounts it lists, and a record of each role update."""
    updates: list[tuple[str, dict]] = []
    client = MagicMock()
    client.auth.admin.list_users = lambda **_: users
    client.auth.admin.update_user_by_id = lambda uid, attrs: updates.append((uid, attrs))
    return client, updates


def _created(actor: uuid.UUID) -> UserCreated:
    return UserCreated(user_id=actor, entity_id=actor, email="new@example.com")


@pytest.mark.asyncio
async def test_the_first_live_user_becomes_server_admin():
    actor = uuid.uuid7()
    client, updates = _gotrue([_user(actor)])

    with patch("apps.auth.infra.user_repository.get_admin_supabase", return_value=client):
        await _bootstrap_first_admin(_NO_SESSION, _created(actor))

    assert updates == [(str(actor), {"app_metadata": {"role": "admin"}})]


@pytest.mark.asyncio
async def test_an_existing_admin_ends_the_bootstrap():
    actor = uuid.uuid7()
    client, updates = _gotrue([_user(uuid.uuid7(), role="admin"), _user(actor)])

    with patch("apps.auth.infra.user_repository.get_admin_supabase", return_value=client):
        await _bootstrap_first_admin(_NO_SESSION, _created(actor))

    assert updates == []


@pytest.mark.asyncio
async def test_a_banned_admin_does_not_cover_the_bootstrap():
    """A banned admin cannot sign in, so the next registrant is promoted."""
    actor = uuid.uuid7()
    client, updates = _gotrue([_user(uuid.uuid7(), role="admin", banned=True), _user(actor)])

    with patch("apps.auth.infra.user_repository.get_admin_supabase", return_value=client):
        await _bootstrap_first_admin(_NO_SESSION, _created(actor))

    assert updates == [(str(actor), {"app_metadata": {"role": "admin"}})]


@pytest.mark.asyncio
async def test_an_anonymized_actor_is_never_promoted():
    """A soft-deleted account is never promoted: the count skips it."""
    actor = uuid.uuid7()
    client, updates = _gotrue([_user(actor, deleted=True)])

    with patch("apps.auth.infra.user_repository.get_admin_supabase", return_value=client):
        await _bootstrap_first_admin(_NO_SESSION, _created(actor))

    assert updates == []
