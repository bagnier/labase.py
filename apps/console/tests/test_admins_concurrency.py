"""The last-admin guard's atomicity (issue #36), across every gate that can remove an admin.

``set_admin`` reads the admin count, then acts on it, as two separate steps with nothing
between them — and so does the account-deletion route's own read-then-check. Two concurrent
callers, through the same gate or two different ones, can both read the same stale count, both
pass the guard, and leave the server with no admin — exactly what each route now prevents by
holding ``lock_last_admin_guard`` (the same orchestration the route itself runs) around the
read.
"""

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
    # A fresh engine bound to this test's event loop — the module-cached one may belong to a
    # different, already-closed loop from an earlier test (the same shape apps/metrics and
    # apps/timeline use around their own concurrent-session fixtures).
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
        # Snapshot now, as a real GoTrue call would: the query already ran and its answer is
        # fixed before the (here, simulated) network hop back delivers it.
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
        # The exact orchestration `update_admin` runs: acquire the guard's lock, then the
        # domain call — set_admin itself never touches the session.
        await lock_last_admin_guard(session)
        return await set_admin(email, is_admin=False)

    try:
        task_a = asyncio.create_task(revoke("bob@example.com", session_a))
        await first_list_entered.wait()

        task_b = asyncio.create_task(revoke("root@example.com", session_b))
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(task_b), timeout=0.2)

        # task_b is not merely slow — it is genuinely parked *waiting* on the guard's advisory
        # lock, visible from a third, independent connection. ``granted`` is false for the
        # request that is queued, not for the one holding it — the holder is a second, separate
        # row, which this leaves out on purpose.
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
    """The gate #80 opened: a console revoke and the target's own account deletion race the
    same invariant through two different routes. Both must go through the same lock, or each
    can read the same stale count and both pass — the symptom of issue #36, by another path."""
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
        # Mirrors `_iter_all_users`, which skips a soft-deleted tombstone: an account the
        # deletion orchestration already marked gone stops being counted, live or not.
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
        # The exact orchestration `update_admin` (console) runs.
        await lock_last_admin_guard(session)
        return await set_admin("bob@example.com", is_admin=False)

    async def root_deletes_own_account(session) -> None:
        # The exact orchestration `account_delete` (profile) runs: acquire the guard's lock,
        # read the directory fresh, then the same shared invariant — no directory write of its
        # own, root simply stops being counted once soft-deleted (mirroring
        # `_iter_all_users`, which skips a ``deleted_at`` tombstone).
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
