"""`DeckRepository`'s own bounded read, run directly against a real, RLS-enforcing session.

The dashboard overview needs an org's most recent decks without loading every one of them —
this holds `recent`'s own contract (bounded, newest first, ties broken by minting order) in
isolation from the overview that calls it.
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import tests.e2e.clock as test_clock
from apps.auth.tests.given_helpers import create_user, delete_user
from apps.learning.domain.models import Deck
from apps.learning.infra.repository import DeckRepository
from apps.organizations.infra.repository import OrganizationRepository
from tests.rls import acting_as


@asynccontextmanager
async def _an_org(session: AsyncSession) -> AsyncGenerator[uuid.UUID]:
    owner = create_user(f"{uuid.uuid4()}@rls.local", "Test1234!")
    try:
        # Rolled back before delete_user, so the FK locks on auth.users are released.
        outer = await session.begin_nested()
        try:
            async with acting_as(session, owner):
                org = await OrganizationRepository(session).create_with_owner(
                    f"Org {uuid.uuid4().hex[:8]}", uuid.UUID(owner)
                )
                yield org.id
        finally:
            await outer.rollback()
    finally:
        delete_user(owner)


@pytest.mark.asyncio
async def test_recent_returns_only_the_newest_decks_up_to_the_limit(db_session: AsyncSession):
    async with _an_org(db_session) as org_id:
        test_clock.set_current_date("2024-01-01")
        for name in ("Oldest", "Middle", "Newest"):
            db_session.add(Deck(org_id=org_id, name=name, position=0))
            await db_session.flush()
            test_clock.advance_days(1)

        recent = await DeckRepository(db_session, org_id).recent(2)

    assert [deck.name for deck in recent] == ["Newest", "Middle"]


@pytest.mark.asyncio
async def test_recent_breaks_a_tied_created_at_by_minting_order(db_session: AsyncSession):
    """`created_at` alone is not a total order: decks created under the same pinned instant
    (a real occurrence — a request, or a test clock nobody advanced) tie, and an `ORDER BY`
    with no secondary key is free to return either one first."""
    async with _an_org(db_session) as org_id:
        test_clock.set_current_date("2024-01-01")
        for name in ("First", "Second", "Third"):
            db_session.add(Deck(org_id=org_id, name=name, position=0))
            await db_session.flush()

        recent = await DeckRepository(db_session, org_id).recent(2)

    assert [deck.name for deck in recent] == ["Third", "Second"]
