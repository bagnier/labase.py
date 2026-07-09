"""Integration: the capture seam really lands rows — log.exception, bus failures, grouping."""

import uuid
from dataclasses import dataclass

import pytest
import pytest_asyncio
import structlog
from sqlalchemy import select

import apps.main  # noqa: F401 — mounts every context, including issues' subscriber
from apps.issues.domain.models import ErrorGroup, IssueStatus
from apps.issues.infra.repository import record_event
from apps.shared.host import host
from apps.shared.observability import capture
from apps.shared.observability.capture import CaptureDrain
from apps.shared.observability.errors import ExceptionCaptured
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
    capture._QUEUE.clear()  # other tests' log.exception calls must not bleed in
    yield
    capture._QUEUE.clear()
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
async def test_log_exception_is_captured():
    """The doctrine: any log.exception is queued and drained into an error group."""
    marker = f"capture-test-{uuid.uuid4().hex}"
    log = structlog.get_logger("labase.test.capture")
    try:
        raise ValueError(marker)
    except ValueError:
        log.exception("test.capture_probe")

    assert capture._QUEUE, "log.exception should have enqueued a capture"
    await CaptureDrain(0).tick()
    assert not capture._QUEUE, "tick must drain the queue"

    group = await _group_titled(marker)
    assert group is not None, "the logged exception should have landed in error_groups"
    assert group.status == IssueStatus.new
    assert group.count == 1


@pytest.mark.asyncio
async def test_failing_bus_handler_is_recorded_as_an_issue():
    marker = f"capture-test-{uuid.uuid4().hex}"

    async def boom(query: _DummyQuery) -> None:
        raise RuntimeError(query.marker)

    host.events.on(_DummyQuery, boom)
    try:
        # collect() logs "query.handler_failed" (log.exception) → the processor enqueues it.
        await host.events.collect(_DummyQuery(marker))  # must not raise: log-and-skip
    finally:
        host.events._subs[_DummyQuery].remove(boom)

    await CaptureDrain(0).tick()
    group = await _group_titled(marker)
    assert group is not None, "the failing handler should have landed in error_groups"
    assert group.status == IssueStatus.new
    assert group.count == 1


@pytest.mark.asyncio
async def test_drain_does_not_recurse_when_a_tracker_handler_fails():
    """The reentrancy guard: a failing ExceptionCaptured handler must not re-enqueue itself."""
    marker = f"capture-test-{uuid.uuid4().hex}"

    async def failing_tracker(_event: ExceptionCaptured) -> None:
        raise RuntimeError("tracker itself is down")

    host.events.on(ExceptionCaptured, failing_tracker)
    try:
        log = structlog.get_logger("labase.test.capture")
        try:
            raise ValueError(marker)
        except ValueError:
            log.exception("test.capture_probe")
        assert len(capture._QUEUE) == 1
        await CaptureDrain(0).tick()  # failing_tracker logs under the guard → no re-enqueue
        assert not capture._QUEUE, "the guard must stop the drain from feeding itself"
    finally:
        host.events._subs[ExceptionCaptured].remove(failing_tracker)

    # The real _record still ran alongside the failing handler, so the group landed.
    assert await _group_titled(marker) is not None


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
