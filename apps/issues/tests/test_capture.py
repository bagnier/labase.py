"""Integration: the capture seam really lands occurrences — log.exception, bus failures."""

import uuid
from dataclasses import dataclass

import pytest
import pytest_asyncio
import structlog
from sqlalchemy import select

import apps.main  # noqa: F401 — mounts every context, including issues' subscriber
from apps.issues.domain.models import Issue, IssueStatus
from apps.issues.infra.repository import record_occurrence
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
        issues = list(
            await session.scalars(select(Issue).where(Issue.title.like("%capture-test%")))
        )
        for issue in issues:
            await session.delete(issue)
        await session.commit()
    await db._admin_engine().dispose()
    _clear_engine_caches()


async def _issue_titled(fragment: str) -> Issue | None:
    async with db.admin_session_factory()() as session:
        return await session.scalar(select(Issue).where(Issue.title.like(f"%{fragment}%")))


@pytest.mark.asyncio
async def test_log_exception_is_captured():
    """The doctrine: any log.exception is queued and drained into an error issue."""
    marker = f"capture-test-{uuid.uuid4().hex}"
    log = structlog.get_logger("labase.test.capture")
    try:
        raise ValueError(marker)
    except ValueError:
        log.exception("test.capture_probe")

    assert capture._QUEUE, "log.exception should have enqueued a capture"
    await CaptureDrain(0).tick()
    assert not capture._QUEUE, "tick must drain the queue"

    issue = await _issue_titled(marker)
    assert issue is not None, "the logged exception should have landed in issues"
    assert issue.status == IssueStatus.new
    assert issue.count == 1


@pytest.mark.asyncio
async def test_failing_bus_handler_is_recorded_as_an_issue():
    marker = f"capture-test-{uuid.uuid4().hex}"

    async def boom(query: _DummyQuery) -> None:
        raise RuntimeError(query.marker)

    host.contribs.provide(_DummyQuery, boom)
    try:
        # collect() logs "query.handler_failed" (log.exception) → the processor enqueues it.
        await host.contribs.collect(_DummyQuery(marker))  # must not raise: log-and-skip
    finally:
        host.contribs._providers[_DummyQuery].remove(boom)

    await CaptureDrain(0).tick()
    issue = await _issue_titled(marker)
    assert issue is not None, "the failing handler should have landed in issues"
    assert issue.status == IssueStatus.new
    assert issue.count == 1


@pytest.mark.asyncio
async def test_drain_does_not_recurse_when_a_tracker_handler_fails():
    """The reentrancy guard: a failing ExceptionCaptured handler must not re-enqueue itself."""
    marker = f"capture-test-{uuid.uuid4().hex}"

    async def failing_tracker(_event: ExceptionCaptured) -> None:
        raise RuntimeError("tracker itself is down")

    capture.on_captured(failing_tracker)
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
        capture._trackers.remove(failing_tracker)

    # The real _record still ran alongside the failing handler, so the issue landed.
    assert await _issue_titled(marker) is not None


@pytest.mark.asyncio
async def test_occurrences_group_by_fingerprint_and_regress_after_resolve():
    marker = f"capture-test-{uuid.uuid4().hex}"

    async def record(version: str) -> Issue:
        async with db.admin_session_factory()() as session:
            recorded = await record_occurrence(
                session,
                fingerprint=marker,
                title=f"ValueError: {marker}",
                version=version,
                context={},
            )
            await session.commit()
            return recorded.issue

    await record("v1")
    issue = await record("v1")
    assert issue.count == 2, "same fingerprint must fold into one issue"

    async with db.admin_session_factory()() as session:
        stored = await session.scalar(select(Issue).where(Issue.fingerprint == marker))
        assert stored is not None
        stored.status = IssueStatus.resolved
        stored.resolved_in_version = "v1"
        await session.commit()

    regressed = await record("v2")
    assert regressed.status == IssueStatus.regressed
