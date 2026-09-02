"""The sign-up seeding chain's actor-gone guard.

``create_personal_org`` (a durable consumer of ``auth.user_created``) and every app's welcome
seeder (durable consumers of ``organizations.created``, routed through ``seed_org_welcome``) run
off the journal, after the actor may already be gone — self-deleted between the fact being
emitted and this delivery. A vanished actor must degrade to a clean no-op, never a parked failure.

The guard is a check followed by a write, which is two statements and therefore a race the check
narrows but cannot close: the write itself is the second half, and it fails with an
``IntegrityError``. Catching that is where the trap sits — the clause names a *type*, and an
``IntegrityError`` says nothing about which constraint broke. A handle collision and the
last-owner trigger arrive spelled exactly like the vanished seat, so a bare ``except`` would file
all three as ``actor_gone`` at ``info``: a line in a window that rolls over, and no issue. What
tells them apart is asking the same question again once the transaction is rolled back — if the
actor is still there, the failure was never about the actor, and it must reach the queue's park,
which is what opens an issue.
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
from apps.organizations.contract.queries import seed_org_welcome, user_exists
from apps.organizations.domain.models import Membership, Organization, OrgRole
from apps.shared.persistence import database as db


def _clear_engine_caches() -> None:
    db._user_engine.cache_clear()
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


async def _insert_a_doomed_membership(session, org_id: uuid.UUID, owner_id: uuid.UUID) -> None:
    """A seeder whose write really violates a foreign key — a genuine ``IntegrityError`` off the
    driver, not a fabricated one, so the session it poisons is poisoned the same way."""
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
    """Regression: ``get_org_owner_id`` reads a real membership row, but the owner it names can
    still vanish before the seeder writes anything keyed on that id."""
    monkeypatch.setattr("apps.organizations.contract.queries.seeding_enabled", lambda: True)
    monkeypatch.setattr(
        "apps.organizations.contract.queries.get_org_owner_id",
        AsyncMock(return_value=uuid.uuid7()),  # a membership pointing at a now-vanished user
    )
    seed = AsyncMock()

    async with db.admin_session_factory()() as session:
        await seed_org_welcome(session, uuid.uuid7(), seed)

    seed.assert_not_called()


@pytest.mark.asyncio
async def test_seed_org_welcome_no_ops_when_the_owner_vanishes_during_the_seeder(monkeypatch):
    """The half the pre-check cannot cover: there when it ran, gone by the time of the write."""
    monkeypatch.setattr("apps.organizations.contract.queries.seeding_enabled", lambda: True)
    monkeypatch.setattr(
        "apps.organizations.contract.queries.get_org_owner_id",
        AsyncMock(return_value=uuid.uuid7()),
    )
    monkeypatch.setattr(
        "apps.organizations.contract.queries.user_exists",
        AsyncMock(side_effect=[True, False]),  # there when checked, gone when asked again
    )

    async with db.admin_session_factory()() as session:
        await seed_org_welcome(session, uuid.uuid7(), _insert_a_doomed_membership)  # must not raise


@pytest.mark.asyncio
async def test_seed_org_welcome_reraises_a_failure_the_owner_is_still_there_to_contradict(
    monkeypatch,
):
    """The same ``IntegrityError``, an owner who never left: not the race, so not this code's to
    absorb. It goes back to the worker, which retries it and eventually parks it into an issue."""
    monkeypatch.setattr("apps.organizations.contract.queries.seeding_enabled", lambda: True)
    monkeypatch.setattr(
        "apps.organizations.contract.queries.get_org_owner_id",
        AsyncMock(return_value=uuid.uuid7()),
    )
    monkeypatch.setattr(
        "apps.organizations.contract.queries.user_exists",
        AsyncMock(return_value=True),  # still there both times it is asked
    )

    async with db.admin_session_factory()() as session:
        with pytest.raises(IntegrityError):
            await seed_org_welcome(session, uuid.uuid7(), _insert_a_doomed_membership)


@pytest.mark.asyncio
async def test_create_org_survives_the_actor_vanishing_between_the_guard_and_the_write(
    monkeypatch,
):
    """Regression: the dev log caught a real ``memberships_user_id_fkey`` violation — the guard's
    existence check and the membership insert are two separate statements, and the actor can
    vanish in between. The write must degrade to the same clean no-op as the guard itself."""
    monkeypatch.setattr(
        "apps.organizations.contract.integration.user_exists",
        # The race, staged: the guard says "go" for a user who is gone by the time it is asked
        # again — which is the question that tells this failure from any other.
        AsyncMock(side_effect=[True, False]),
    )
    ghost = uuid.uuid7()  # never created, so the membership insert genuinely violates the FK
    event = UserCreated(user_id=ghost, entity_id=ghost, email="ghost@signup-seeding.local")

    async with db.admin_session_factory()() as session:
        await _create_org(session, event)  # must not raise
        orphaned = await session.scalar(
            select(Organization).where(Organization.name == event.email)
        )

    assert orphaned is None


@pytest.mark.asyncio
async def test_create_org_reraises_a_failure_the_actor_is_still_there_to_contradict(monkeypatch):
    """``except IntegrityError`` names a type, not a cause: a handle collision and the last-owner
    trigger arrive spelled the same way as the vanished seat. Absorbing those as ``actor_gone``
    would bury a real defect under an ``info`` line — so an actor who is still there sends the
    failure back to the worker, whose park is what opens the issue."""
    monkeypatch.setattr(
        "apps.organizations.contract.integration.user_exists",
        AsyncMock(return_value=True),  # still there both times it is asked
    )
    ghost = uuid.uuid7()
    event = UserCreated(user_id=ghost, entity_id=ghost, email="ghost2@signup-seeding.local")

    async with db.admin_session_factory()() as session:
        with pytest.raises(IntegrityError):
            await _create_org(session, event)
