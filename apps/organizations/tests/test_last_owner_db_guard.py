"""The last-owner invariant has a DB backstop, not just the Python domain guard.

`ensure_not_last_owner` only protects the in-app routes; a raw PostgREST/supabase-js client
holding the JWT can DELETE/UPDATE memberships directly. This drives the trigger the way
that client would — direct SQL on the ``authenticated`` RLS session, bypassing the service.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.tests.given_helpers import create_user, delete_user
from apps.organizations.infra.repository import OrganizationRepository
from tests.rls import acting_as


@pytest.mark.asyncio
async def test_db_trigger_blocks_orphaning_the_last_owner(db_session: AsyncSession):
    email1 = f"{uuid.uuid4()}@rls.local"
    email2 = f"{uuid.uuid4()}@rls.local"
    uid1 = create_user(email1, "Test1234!")
    uid2 = create_user(email2, "Test1234!")
    try:
        async with acting_as(db_session, uid1):
            # One savepoint holding every seeded row; rolled back before delete_user so the
            # FK KEY SHARE locks on auth.users are released (else the GoTrue delete deadlocks).
            outer = await db_session.begin_nested()
            try:
                org = await OrganizationRepository(db_session).create_with_owner(
                    f"Org {uuid.uuid4().hex[:8]}", uuid.UUID(uid1)
                )
                await db_session.flush()

                # Direct DELETE of the sole owner is rejected by the DB trigger.
                with pytest.raises(IntegrityError) as exc:
                    async with db_session.begin_nested():
                        await db_session.execute(
                            text("delete from memberships where org_id = :o and user_id = :u"),
                            {"o": str(org.id), "u": uid1},
                        )
                assert "last owner" in str(exc.value).lower()

                # Demoting the sole owner to member is rejected the same way.
                with pytest.raises(IntegrityError) as exc:
                    async with db_session.begin_nested():
                        await db_session.execute(
                            text(
                                "update memberships set role = 'member' "
                                "where org_id = :o and user_id = :u"
                            ),
                            {"o": str(org.id), "u": uid1},
                        )
                assert "last owner" in str(exc.value).lower()

                # With a co-owner present, removing one owner is allowed (no over-blocking).
                await db_session.execute(
                    text(
                        "insert into memberships (org_id, user_id, role) values (:o, :u, 'owner')"
                    ),
                    {"o": str(org.id), "u": uid2},
                )
                await db_session.execute(
                    text("delete from memberships where org_id = :o and user_id = :u"),
                    {"o": str(org.id), "u": uid1},
                )
            finally:
                await outer.rollback()
    finally:
        delete_user(uid1)
        delete_user(uid2)
