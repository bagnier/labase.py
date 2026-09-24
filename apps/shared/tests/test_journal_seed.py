"""``seed_fact`` fills in whichever pinned name the caller left unset — not both or neither.

An arrangement that pins one name by hand (a test standing up a closed account, still inside a
live org) needs the *other* name resolved the ordinary way, exactly as the write path would have
left it. The all-or-nothing guard treated the two names as one unit: setting either one skipped
resolving both, so the org name a real org fixture set up went missing too.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from apps.shared.events.models import BusinessEventRecord
from apps.shared.persistence import database as db
from apps.shared.persistence.database import admin_session_factory
from apps.shared.tests.journal_seed import seed_fact

_ORG_NAME = "Acme Corp"


@pytest_asyncio.fixture(autouse=True)
async def _isolated_engine():
    # This module opens its own sessions outside any driver fixture, on this test's event loop —
    # cleared going in and disposed going out so a driver-based test on another loop never inherits
    # a dead pool (the "Event loop is closed" failure apps/timeline/tests/conftest.py guards against
    # the same way).
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()
    yield
    await db._admin_engine().dispose()
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


async def _make_org() -> uuid.UUID:
    org = uuid.uuid7()
    async with admin_session_factory()() as session:
        await session.execute(
            text("INSERT INTO organizations (id, name, handle) VALUES (:i, :n, :h)"),
            {"i": org, "n": _ORG_NAME, "h": f"acme-{org.hex[:8]}"},
        )
        await session.commit()
    return org


async def _delete_org(org: uuid.UUID) -> None:
    async with admin_session_factory()() as session:
        await session.execute(text("DELETE FROM organizations WHERE id = :i"), {"i": org})
        await session.commit()


async def _seeded_org_name(user_id: uuid.UUID) -> str | None:
    async with admin_session_factory()() as session:
        return await session.scalar(
            text("SELECT org_name FROM business_events WHERE user_id = :u"), {"u": user_id}
        )


@pytest.mark.asyncio
async def test_seed_fact_still_resolves_the_org_name_when_only_the_user_name_is_pinned():
    org = await _make_org()
    try:
        actor = uuid.uuid7()
        await seed_fact(
            BusinessEventRecord(
                app_name="sample",
                verb="created",
                user_id=actor,
                user_name="gone@example.com",
                org_id=org,
            )
        )

        org_name = await _seeded_org_name(actor)
    finally:
        await _delete_org(org)

    assert org_name == _ORG_NAME
