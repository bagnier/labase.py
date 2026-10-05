"""The sign-up chain's reactions when the user or org is gone by delivery: a clean no-op, also
when the write races the check. An ``IntegrityError`` while both remain is another bug, left to
the worker to retry and park.
"""

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from apps.auth.contract.events import UserCreated
from apps.auth.tests.given_helpers import create_user, delete_user
from apps.organizations.contract.integration import _create_org
from apps.organizations.contract.queries import org_exists, seed_org_welcome, user_exists
from apps.organizations.domain.models import Membership, Organization, OrgRole
from apps.organizations.infra.repository import OrganizationRepository
from apps.shared.persistence import database as db


def _clear_engine_caches() -> None:
    db._user_engine.cache_clear()
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest_asyncio.fixture(autouse=True)
async def _fresh_engines():
    """Fresh engines for this test's loop."""
    _clear_engine_caches()
    yield
    await db._admin_engine().dispose()
    _clear_engine_caches()


async def _insert_a_doomed_membership(session, org_id: uuid.UUID, owner_id: uuid.UUID) -> None:
    """A real foreign-key violation, poisoning the session as a real one does."""
    session.add(Membership(org_id=org_id, user_id=owner_id, role=OrgRole.owner))
    await session.flush()


@pytest.mark.asyncio
async def test_user_exists_is_true_for_a_live_user():
    uid = create_user(f"{uuid.uuid4()}@signup-seeding.local", "Test1234!")
    try:
        async with db.admin_session_factory()() as session:
            assert await user_exists(session, uuid.UUID(uid)) is True
    finally:
        delete_user(uid)


@pytest.mark.asyncio
async def test_user_exists_is_false_for_an_unknown_user():
    async with db.admin_session_factory()() as session:
        assert await user_exists(session, uuid.uuid7()) is False


@pytest.mark.asyncio
async def test_seed_org_welcome_no_ops_when_the_resolved_owner_is_gone(monkeypatch):
    monkeypatch.setattr("apps.organizations.contract.queries.seeding_enabled", lambda: True)
    monkeypatch.setattr(
        "apps.organizations.contract.queries.get_org_owner_id",
        AsyncMock(return_value=uuid.uuid7()),  # a vanished owner
    )
    seed = AsyncMock()

    async with db.admin_session_factory()() as session:
        await seed_org_welcome(session, uuid.uuid7(), seed)

    seed.assert_not_called()


@pytest.mark.asyncio
async def test_org_exists_is_true_for_a_live_org():
    owner_id = create_user(f"{uuid.uuid4()}@signup-seeding.local", "Test1234!")
    try:
        async with db.admin_session_factory()() as session:
            org = await OrganizationRepository(session).create_with_owner(
                name="Org exists test", user_id=uuid.UUID(owner_id)
            )
            await session.commit()
            assert await org_exists(session, org.id) is True
    finally:
        delete_user(owner_id)


@pytest.mark.asyncio
async def test_org_exists_is_false_for_an_unknown_org():
    async with db.admin_session_factory()() as session:
        assert await org_exists(session, uuid.uuid7()) is False


@pytest.mark.asyncio
async def test_seed_org_welcome_no_ops_when_the_owner_vanishes_during_the_seeder(monkeypatch):
    monkeypatch.setattr("apps.organizations.contract.queries.seeding_enabled", lambda: True)
    monkeypatch.setattr(
        "apps.organizations.contract.queries.get_org_owner_id",
        AsyncMock(return_value=uuid.uuid7()),
    )
    monkeypatch.setattr(
        "apps.organizations.contract.queries.user_exists",
        AsyncMock(side_effect=[True, False]),
    )

    async with db.admin_session_factory()() as session:
        await seed_org_welcome(session, uuid.uuid7(), _insert_a_doomed_membership)


@pytest.mark.asyncio
async def test_seed_org_welcome_no_ops_when_the_org_vanishes_during_the_seeder(monkeypatch):
    """The owner remains but the org is gone: the insert fails on the org's foreign key."""
    owner_id = create_user(f"{uuid.uuid4()}@signup-seeding.local", "Test1234!")
    try:
        monkeypatch.setattr("apps.organizations.contract.queries.seeding_enabled", lambda: True)
        monkeypatch.setattr(
            "apps.organizations.contract.queries.get_org_owner_id",
            AsyncMock(return_value=uuid.UUID(owner_id)),
        )
        ghost_org = uuid.uuid7()

        async with db.admin_session_factory()() as session:
            await seed_org_welcome(session, ghost_org, _insert_a_doomed_membership)
    finally:
        delete_user(owner_id)


@pytest.mark.asyncio
async def test_seed_org_welcome_reraises_a_failure_neither_the_owner_nor_the_org_contradicts(
    monkeypatch,
):
    """Owner and org both remain: the error goes back to the worker."""
    owner_id = create_user(f"{uuid.uuid4()}@signup-seeding.local", "Test1234!")
    try:
        async with db.admin_session_factory()() as session:
            org = await OrganizationRepository(session).create_with_owner(
                name="Reraise test", user_id=uuid.UUID(owner_id)
            )
            await session.commit()

            monkeypatch.setattr("apps.organizations.contract.queries.seeding_enabled", lambda: True)
            monkeypatch.setattr(
                "apps.organizations.contract.queries.get_org_owner_id",
                AsyncMock(return_value=uuid.UUID(owner_id)),
            )
            # The insert collides on the membership primary key.
            with pytest.raises(IntegrityError):
                await seed_org_welcome(session, org.id, _insert_a_doomed_membership)
    finally:
        delete_user(owner_id)


@pytest.mark.asyncio
async def test_create_org_survives_the_actor_vanishing_between_the_guard_and_the_write(
    monkeypatch,
):
    """The user vanishes between the check and the membership insert."""
    monkeypatch.setattr(
        "apps.organizations.contract.integration.user_exists",
        AsyncMock(side_effect=[True, False]),
    )
    ghost = uuid.uuid7()
    event = UserCreated(user_id=ghost, entity_id=ghost, email="ghost@signup-seeding.local")

    async with db.admin_session_factory()() as session:
        await _create_org(session, event)
        orphaned = await session.scalar(
            select(Organization).where(Organization.name == event.email)
        )

    assert orphaned is None


@pytest.mark.asyncio
async def test_create_org_still_creates_a_personal_org_for_an_invitee_who_joined_first():
    """An invitee may already be a member when ``UserCreated`` is delivered: they still get a
    personal org."""
    owner_id = create_user(f"{uuid.uuid4()}@signup-seeding.local", "Test1234!")
    invitee_id = create_user(f"{uuid.uuid4()}@signup-seeding.local", "Test1234!")
    try:
        async with db.admin_session_factory()() as session:
            org = await OrganizationRepository(session).create_with_owner(
                name="Someone else's org",
                user_id=uuid.UUID(owner_id),
            )
            session.add(
                Membership(org_id=org.id, user_id=uuid.UUID(invitee_id), role=OrgRole.member)
            )
            await session.commit()

            event = UserCreated(
                user_id=uuid.UUID(invitee_id),
                entity_id=uuid.UUID(invitee_id),
                email="invitee@signup-seeding.local",
            )
            await _create_org(session, event)
            await session.commit()

            memberships = await OrganizationRepository(session).list_with_role_for_user(
                uuid.UUID(invitee_id)
            )
        roles_by_org_name = {org.name: role for org, role in memberships}
        assert roles_by_org_name == {
            "Someone else's org": OrgRole.member,
            "invitee@signup-seeding.local": OrgRole.owner,
        }
    finally:
        delete_user(owner_id)
        delete_user(invitee_id)


@pytest.mark.asyncio
async def test_create_org_still_creates_a_personal_org_for_a_user_who_owns_a_team_org_first():
    """A team org created before delivery does not count; a redelivery after the personal org
    exists is a no-op."""
    user_id = create_user(f"{uuid.uuid4()}@signup-seeding.local", "Test1234!")
    try:
        async with db.admin_session_factory()() as session:
            await OrganizationRepository(session).create_with_owner(
                name="A team org",
                user_id=uuid.UUID(user_id),
            )
            await session.commit()

            event = UserCreated(
                user_id=uuid.UUID(user_id),
                entity_id=uuid.UUID(user_id),
                email="team-owner@signup-seeding.local",
            )
            await _create_org(session, event)
            await _create_org(session, event)  # redelivery
            await session.commit()

            memberships = await OrganizationRepository(session).list_with_role_for_user(
                uuid.UUID(user_id)
            )
        facts_by_org_name = {org.name: (role, org.is_personal) for org, role in memberships}
        assert facts_by_org_name == {
            "A team org": (OrgRole.owner, False),
            "team-owner@signup-seeding.local": (OrgRole.owner, True),
        }
    finally:
        delete_user(user_id)


@pytest.mark.asyncio
async def test_create_org_reraises_a_failure_the_actor_is_still_there_to_contradict(monkeypatch):
    """The user remains, so the error is not theirs: back to the worker."""
    monkeypatch.setattr(
        "apps.organizations.contract.integration.user_exists",
        AsyncMock(return_value=True),
    )
    ghost = uuid.uuid7()
    event = UserCreated(user_id=ghost, entity_id=ghost, email="ghost2@signup-seeding.local")

    async with db.admin_session_factory()() as session:
        with pytest.raises(IntegrityError):
            await _create_org(session, event)
