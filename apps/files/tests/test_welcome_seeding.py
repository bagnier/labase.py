"""The welcome seeder's two stores, and what happens when only one of them takes the write.

``_seed_welcome`` uploads the file *then* records the row. Storage has no transaction to join, so
a rollback returns the row and leaves the object: every failed attempt strands a blob at a fresh
``uuid7`` path that no row will ever name again, and the retry — which no-ops once the owner is
confirmed gone — never comes back for it. The seeder owns the upload, so the seeder is what has to
undo it; ``seed_org_welcome`` above it cannot, having no idea an upload happened at all.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

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
async def test_a_seeder_whose_row_is_refused_takes_its_uploaded_file_back():
    """Regression: the dev log caught a real ``org_files_uploaded_by_fkey`` violation, and each
    attempt left one unreferenced ``welcome.txt`` behind."""
    ghost_org, ghost_owner = uuid.uuid7(), uuid.uuid7()  # neither exists: the insert cannot land

    async with db.admin_session_factory()() as session:
        with pytest.raises(IntegrityError):
            await _seed_welcome(session, ghost_org, ghost_owner)

    stranded = await _objects_under(ghost_org)
    if stranded:  # a red run leaves the very blob this test is about
        await admin_storage().from_(bucket()).remove([f"{ghost_org}/{n}" for n in stranded])

    assert stranded == []
