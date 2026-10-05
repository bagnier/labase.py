"""The welcome file: nothing is uploaded once the owner or the org is gone."""

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
    """Fresh engines for this test's loop."""
    _clear_engine_caches()
    yield
    await db._admin_engine().dispose()
    _clear_engine_caches()


async def _objects_under(org_id: uuid.UUID) -> list[str]:
    listed = await admin_storage().from_(bucket()).list(str(org_id))
    return [entry["name"] for entry in listed]


@pytest.mark.asyncio
async def test_a_seeder_whose_owner_is_already_gone_is_a_clean_no_op():
    ghost_org, ghost_owner = uuid.uuid7(), uuid.uuid7()

    async with db.admin_session_factory()() as session:
        try:
            await _seed_welcome(session, ghost_org, ghost_owner)
        finally:
            stranded = await _objects_under(ghost_org)
            if stranded:  # cleanup after a failure
                await admin_storage().from_(bucket()).remove([f"{ghost_org}/{n}" for n in stranded])

    assert stranded == []


@pytest.mark.asyncio
async def test_a_seeder_whose_org_is_already_gone_strands_no_object():
    """The rollback would undo the row, not the uploaded object."""
    owner_id = create_user(f"{uuid.uuid4()}@welcome-seeding.local", "Test1234!")
    ghost_org = uuid.uuid7()

    try:
        async with db.admin_session_factory()() as session:
            try:
                await _seed_welcome(session, ghost_org, uuid.UUID(owner_id))
            finally:
                stranded = await _objects_under(ghost_org)
                if stranded:  # cleanup after a failure
                    await (
                        admin_storage()
                        .from_(bucket())
                        .remove([f"{ghost_org}/{n}" for n in stranded])
                    )
    finally:
        delete_user(owner_id)

    assert stranded == []
