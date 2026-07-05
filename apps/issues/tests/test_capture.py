"""Integration: the capture seam really lands rows — bus failures and grouping."""

import uuid
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy import select

import apps.main  # noqa: F401 — mounts every context, including issues' subscriber
from apps.issues.domain.models import ErrorGroup, IssueStatus
from apps.issues.infra.repository import record_event
from apps.shared.host import host
from apps.shared.persistence import database as db


@dataclass(frozen=True)
class _DummyQuery:
    marker: str


def _clear_engine_caches() -> None:
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest_asyncio.fixture(autouse=True)
async def issues_isolation():
    _clear_engine_caches()
    yield
    async with db.admin_session_factory()() as session:
        groups = list(
            await session.scalars(select(ErrorGroup).where(ErrorGroup.title.like("%capture-test%")))
        )
        for group in groups:
            await session.delete(group)
        await session.commit()
    await db._admin_engine().dispose()
    _clear_engine_caches()


async def _group_titled(fragment: str) -> ErrorGroup | None:
    async with db.admin_session_factory()() as session:
        return await session.scalar(
            select(ErrorGroup).where(ErrorGroup.title.like(f"%{fragment}%"))
        )


@pytest.mark.asyncio
async def test_failing_bus_handler_is_recorded_as_an_issue():
    marker = f"capture-test-{uuid.uuid4().hex}"

    async def boom(query: _DummyQuery) -> None:
        raise RuntimeError(query.marker)

    host.events.on(_DummyQuery, boom)
    try:
        await host.events.collect(_DummyQuery(marker))  # must not raise: log-and-skip
    finally:
        host.events._subs[_DummyQuery].remove(boom)

    group = await _group_titled(marker)
    assert group is not None, "the failing handler should have landed in error_groups"
    assert group.status == IssueStatus.new
    assert group.count == 1


@pytest.mark.asyncio
async def test_events_group_by_fingerprint_and_regress_after_resolve():
    marker = f"capture-test-{uuid.uuid4().hex}"

    async def record(version: str) -> ErrorGroup:
        async with db.admin_session_factory()() as session:
            recorded = await record_event(
                session,
                fingerprint=marker,
                title=f"ValueError: {marker}",
                version=version,
                context={},
            )
            await session.commit()
            return recorded.group

    await record("v1")
    group = await record("v1")
    assert group.count == 2, "same fingerprint must fold into one group"

    async with db.admin_session_factory()() as session:
        stored = await session.scalar(select(ErrorGroup).where(ErrorGroup.fingerprint == marker))
        assert stored is not None
        stored.status = IssueStatus.resolved
        stored.resolved_in_version = "v1"
        await session.commit()

    regressed = await record("v2")
    assert regressed.status == IssueStatus.regressed
