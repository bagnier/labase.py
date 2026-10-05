"""The last-admin guard under concurrency: every path that can remove an admin holds
``lock_last_admin_guard`` around its count-then-act."""

import asyncio
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from apps.auth.contract.admin import (
    LastAdminViolation,
    ensure_not_last_admin,
    lock_last_admin_guard,
)
from apps.auth.infra.admin_guard import _LAST_ADMIN_GUARD_LOCK_KEY
from apps.auth.infra.user_repository import UserAdminStatus
from apps.console.domain.admins import set_admin
from apps.shared.persistence import database as db


def _clear_engine_caches() -> None:
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest_asyncio.fixture(autouse=True)
async def admin_guard_isolation():
    # A fresh engine on this loop: the cached one may belong to a closed loop.
    _clear_engine_caches()
    yield
    await db._admin_engine().dispose()
    _clear_engine_caches()


@pytest.mark.asyncio
async def test_two_concurrent_revocations_leave_the_server_with_one_admin(monkeypatch):
    root_id, bob_id = uuid.uuid7(), uuid.uuid7()
    admin_flags = {root_id: True, bob_id: True}
    list_calls = 0
    first_list_entered = asyncio.Event()
    let_first_list_return = asyncio.Event()

    async def fake_list_server_admins() -> list[UserAdminStatus]:
        nonlocal list_calls
        list_calls += 1
        # Snapshot now, as a real call fixes its answer before the network hop.
        snapshot = dict(admin_flags)
        if list_calls == 1:
            first_list_entered.set()
            await let_first_list_return.wait()
        return [
            UserAdminStatus(user_id=root_id, email="root@example.com", is_admin=snapshot[root_id]),
            UserAdminStatus(user_id=bob_id, email="bob@example.com", is_admin=snapshot[bob_id]),
        ]

    async def fake_set_server_admin(user_id: uuid.UUID, *, is_admin: bool) -> None:
        admin_flags[user_id] = is_admin

    monkeypatch.setattr("apps.console.domain.admins.list_server_admins", fake_list_server_admins)
    monkeypatch.setattr("apps.console.domain.admins.set_server_admin", fake_set_server_admin)

    session_a = db.admin_session_factory()()
    session_b = db.admin_session_factory()()
    observer = db.admin_session_factory()()

    async def revoke(email: str, session) -> tuple[list[UserAdminStatus], bool, uuid.UUID]:
        # As `update_admin`: the lock, then the domain call.
        await lock_last_admin_guard(session)
        return await set_admin(email, is_admin=False)

    try:
        task_a = asyncio.create_task(revoke("bob@example.com", session_a))
        await first_list_entered.wait()

        task_b = asyncio.create_task(revoke("root@example.com", session_b))
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(task_b), timeout=0.2)

        # task_b waits on the advisory lock, seen from a third connection (``granted`` false).
        waiting_on_guard_lock = (
            await observer.execute(
                text(
                    "select count(*) from pg_locks"
                    " where locktype = 'advisory' and objid = :key and not granted"
                ),
                {"key": _LAST_ADMIN_GUARD_LOCK_KEY},
            )
        ).scalar_one()
        assert waiting_on_guard_lock == 1

        let_first_list_return.set()
        await task_a
        await session_a.commit()
        with pytest.raises(LastAdminViolation):
            await task_b
    finally:
        await session_a.close()
        await session_b.close()
        await observer.close()

    assert admin_flags == {root_id: True, bob_id: False}


@pytest.mark.asyncio
async def test_a_concurrent_revoke_and_self_deletion_leave_the_server_with_one_admin(monkeypatch):
    """A console revoke and the target's self-deletion take the same lock."""
    root_id, bob_id = uuid.uuid7(), uuid.uuid7()
    admin_flags = {root_id: True, bob_id: True}
    deleted: set[uuid.UUID] = set()
    list_calls = 0
    first_list_entered = asyncio.Event()
    let_first_list_return = asyncio.Event()

    async def fake_list_server_admins() -> list[UserAdminStatus]:
        nonlocal list_calls
        list_calls += 1
        snapshot = dict(admin_flags)
        # Like `_iter_all_users`: a soft-deleted account no longer counts.
        live_snapshot = {uid: is_admin for uid, is_admin in snapshot.items() if uid not in deleted}
        if list_calls == 1:
            first_list_entered.set()
            await let_first_list_return.wait()
        return [
            UserAdminStatus(user_id=uid, email=email, is_admin=is_admin)
            for uid, email in ((root_id, "root@example.com"), (bob_id, "bob@example.com"))
            if (is_admin := live_snapshot.get(uid)) is not None
        ]

    async def fake_set_server_admin(user_id: uuid.UUID, *, is_admin: bool) -> None:
        admin_flags[user_id] = is_admin

    monkeypatch.setattr("apps.console.domain.admins.list_server_admins", fake_list_server_admins)
    monkeypatch.setattr("apps.console.domain.admins.set_server_admin", fake_set_server_admin)

    session_a = db.admin_session_factory()()
    session_b = db.admin_session_factory()()

    async def revoke_bob(session) -> tuple[list[UserAdminStatus], bool, uuid.UUID]:
        # As `update_admin` (console).
        await lock_last_admin_guard(session)
        return await set_admin("bob@example.com", is_admin=False)

    async def root_deletes_own_account(session) -> None:
        # As `account_delete` (profile): the lock, a fresh read, the same invariant.
        await lock_last_admin_guard(session)
        current = await fake_list_server_admins()
        target_is_admin = any(u.user_id == root_id and u.is_admin for u in current)
        admin_count = sum(1 for u in current if u.is_admin)
        ensure_not_last_admin(
            removes_admin=True, target_is_admin=target_is_admin, admin_count=admin_count
        )
        deleted.add(root_id)

    try:
        task_a = asyncio.create_task(revoke_bob(session_a))
        await first_list_entered.wait()

        task_b = asyncio.create_task(root_deletes_own_account(session_b))
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(task_b), timeout=0.2)

        let_first_list_return.set()
        await task_a
        await session_a.commit()
        with pytest.raises(LastAdminViolation):
            await task_b
    finally:
        await session_a.close()
        await session_b.close()

    assert admin_flags == {root_id: True, bob_id: False}
    assert root_id not in deleted
