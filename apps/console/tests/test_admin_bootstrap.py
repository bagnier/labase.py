"""The first-admin bootstrap — the console's reaction to ``UserCreated``.

The policy: the first registered user becomes server admin. The fact is delivered off the journal,
minutes to days later, so the actor may no longer be a live account — and the admin count only
looks at live accounts. Whoever the bootstrap promotes must therefore be countable, or the count
stays at zero and every following ``UserCreated`` promotes someone else forever.
"""

import uuid
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.contract.events import UserCreated
from apps.console.contract.integration import _bootstrap_first_admin

_NO_SESSION = cast(AsyncSession, None)  # the handler runs on the GoTrue admin API, not the session


def _user(user_id: uuid.UUID, *, role: str | None = None, deleted: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=str(user_id),
        email=f"{user_id}@example.com",
        app_metadata={"role": role} if role else {},
        deleted_at="2026-08-20T00:00:00Z" if deleted else None,
    )


def _gotrue(users: list[SimpleNamespace]) -> tuple[MagicMock, list[tuple[str, dict]]]:
    """A stubbed GoTrue admin API (a service we own): the accounts the directory lists, and a
    record of every role update handed to it — the observable outcome of the bootstrap."""
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
async def test_an_anonymized_actor_is_never_promoted():
    """Regression: a dev database full of soft-deleted test accounts. The count skips tombstones,
    so promoting one leaves it at zero — 170 tombstones ended up wearing ``role=admin`` and the
    bootstrap never converged."""
    actor = uuid.uuid7()
    client, updates = _gotrue([_user(actor, deleted=True)])

    with patch("apps.auth.infra.user_repository.get_admin_supabase", return_value=client):
        await _bootstrap_first_admin(_NO_SESSION, _created(actor))

    assert updates == []
