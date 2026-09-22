"""The last-admin guard's atomicity (issue #36).

``set_admin`` reads the admin count, then acts on it, as two separate steps with nothing
between them: two concurrent revocations can both read the same stale count, both pass the
guard, and leave the server with no admin — exactly what the route now prevents by holding
``lock_last_admin_guard`` (the same orchestration ``update_admin`` runs) around the call.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import text

from apps.auth.infra.user_repository import UserAdminStatus
from apps.console.domain.admins import LastAdminViolation, set_admin
from apps.console.infra.repository import lock_last_admin_guard
from apps.shared.persistence import database as db


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

    async def fake_find_user_id_by_email(email: str) -> uuid.UUID | None:
        return {"root@example.com": root_id, "bob@example.com": bob_id}[email]

    monkeypatch.setattr("apps.console.domain.admins.list_server_admins", fake_list_server_admins)
    monkeypatch.setattr("apps.console.domain.admins.set_server_admin", fake_set_server_admin)
    monkeypatch.setattr(
        "apps.console.domain.admins.find_user_id_by_email", fake_find_user_id_by_email
    )

    # A fresh engine bound to this test's event loop — the module-cached one may belong to a
    # different, already-closed loop from an earlier test.
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()
    session_a = db.admin_session_factory()()
    session_b = db.admin_session_factory()()
    observer = db.admin_session_factory()()

    async def revoke(email: str, session) -> list[UserAdminStatus]:
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

        # task_b is not merely slow — it is genuinely parked on a Postgres advisory lock,
        # visible from a third, independent connection.
        held_advisory_locks = (
            await observer.execute(
                text("select count(*) from pg_locks where locktype = 'advisory' and granted")
            )
        ).scalar_one()
        assert held_advisory_locks == 1

        let_first_list_return.set()
        await task_a
        await session_a.commit()
        with pytest.raises(LastAdminViolation):
            await task_b
    finally:
        await session_a.close()
        await session_b.close()
        await observer.close()
        await db._admin_engine().dispose()
        db._admin_engine.cache_clear()
        db.admin_session_factory.cache_clear()

    assert admin_flags == {root_id: True, bob_id: False}
