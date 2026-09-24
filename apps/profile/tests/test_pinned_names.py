"""Which name a fact pins for its actor when the account never set a handle.

``EventRepository.pinned_names`` resolves the actor's handle at write time to pin it onto the
fact's ``user_name`` column (see ``apps/timeline/tests/test_actor_naming.py``). ``profiles.handle``
is only ever set by visiting ``/profile`` (``ProfileRepository.auto_handle``), so an account that
emits a fact without ever having opened it still has nothing to pin there — ``profiles.email``,
set atomically at signup, is the one column always available instead.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.tests.given_helpers import create_user, delete_user
from apps.shared.events.repository import EventRepository
from tests.rls import acting_as


@pytest.mark.asyncio
async def test_pinned_names_falls_back_to_the_email_when_the_handle_is_still_unset(
    db_session: AsyncSession,
):
    email = f"{uuid.uuid4()}@pinned-fallback.example"
    uid = create_user(email, "Test1234!")
    try:
        async with acting_as(db_session, uid):
            user_name, org_name = await EventRepository(db_session).pinned_names(
                uuid.UUID(uid), None
            )
        assert (user_name, org_name) == (email, None)
    finally:
        delete_user(uid)
