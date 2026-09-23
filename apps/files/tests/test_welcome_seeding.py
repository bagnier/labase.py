"""The welcome seeder, and what a vanished owner does to its handoff.

``_seed_welcome`` checks the owner is still there before it uploads anything: a durable
consumer whose subject already left is a clean no-op, never a compensation reaching back into
Storage for an object it just placed there.
"""

import uuid

import pytest
import pytest_asyncio

from apps.auth.tests.given_helpers import create_user, delete_user
from apps.files.contract.integration import _seed_welcome
from apps.shared.persistence import database as db
from apps.shared.persistence.storage import admin_storage, bucket


def _clear_engine_caches() -> None:
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engines():
    """Each test gets its own event loop; the engines are ``lru_cache``d singletons bound to
    whichever loop built them, so a prior test's cached engine breaks on this one's loop."""
    _clear_engine_caches()
    yield
    await db._admin_engine().dispose()
    _clear_engine_caches()


async def _objects_under(org_id: uuid.UUID) -> list[str]:
    listed = await admin_storage().from_(bucket()).list(str(org_id))
    return [entry["name"] for entry in listed]


@pytest.mark.asyncio
async def test_a_seeder_whose_owner_is_already_gone_is_a_clean_no_op():
    ghost_org, ghost_owner = uuid.uuid7(), uuid.uuid7()  # neither exists

    async with db.admin_session_factory()() as session:
        try:
            await _seed_welcome(session, ghost_org, ghost_owner)
        finally:
            stranded = await _objects_under(ghost_org)
            if stranded:  # a red run leaves the very blob this test is about
                await admin_storage().from_(bucket()).remove([f"{ghost_org}/{n}" for n in stranded])

    assert stranded == []


@pytest.mark.asyncio
async def test_a_seeder_whose_org_is_already_gone_strands_no_object():
    """Regression (#75): the owner check alone let the seeder past a vanished *org* — the
    upload landed in Storage before the insert failed on the org's own foreign key, and the
    rollback that follows undoes the row but not the object it already wrote."""
    owner_id = create_user(f"{uuid.uuid4()}@welcome-seeding.local", "Test1234!")
    ghost_org = uuid.uuid7()  # never created

    try:
        async with db.admin_session_factory()() as session:
            try:
                await _seed_welcome(session, ghost_org, uuid.UUID(owner_id))
            finally:
                stranded = await _objects_under(ghost_org)
                if stranded:  # a red run leaves the very blob this test is about
                    await (
                        admin_storage()
                        .from_(bucket())
                        .remove([f"{ghost_org}/{n}" for n in stranded])
                    )
    finally:
        delete_user(owner_id)

    assert stranded == []
