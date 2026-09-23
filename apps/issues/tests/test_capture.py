"""Integration: a log.exception really lands as an occurrence, wherever it was written."""

import uuid
from dataclasses import dataclass

import pytest
import pytest_asyncio
import structlog
from sqlalchemy import select

import apps.main  # noqa: F401 — mounts every context, including issues' subscriber
from apps.issues.contract.queries import search_issue_occurrences
from apps.issues.domain.models import Issue, IssueStatus
from apps.issues.infra.repository import see_occurrence
from apps.shared.events.models import BusinessEventRecord
from apps.shared.integration.host import host
from apps.shared.logs import capture
from apps.shared.logs.capture import CaptureDrain, ExceptionCaptured
from apps.shared.persistence import database as db

# The line these tests fabricate stands in for ordinary application code — the doctrine is
# "any log.exception", not "one written here". Stated rather than taken from ``__name__``
# because the logger name is an input now: it picks the timeline source and the app axis, and
# it is stored in the occurrence's context.
_PROBE_LOGGER = "apps.todo.infra.router"


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
    """The doctrine: any log.exception is queued and drained into an issue."""
    marker = f"capture-test-{uuid.uuid4().hex}"
    log = structlog.get_logger(_PROBE_LOGGER)
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
    assert issue.occurrence_count == 1


@pytest.mark.asyncio
async def test_an_occurrence_keeps_the_logger_that_raised():
    """The pivot back to the log sink: an occurrence and the line that produced it correlate on
    the logger, which is what tells a reader *where* in the code the issue came from."""
    marker = f"capture-test-{uuid.uuid4().hex}"
    log = structlog.get_logger(_PROBE_LOGGER)
    try:
        raise ValueError(marker)
    except ValueError:
        log.exception("test.capture_probe")
    await CaptureDrain(0).tick()

    async with db.admin_session_factory()() as session:
        found = await search_issue_occurrences(session, text=marker)

    assert [o.context.get("logger") for o in found] == [_PROBE_LOGGER]


@pytest.mark.asyncio
async def test_a_failing_contribution_provider_is_tracked_as_an_issue():
    marker = f"capture-test-{uuid.uuid4().hex}"

    async def boom(query: _DummyQuery) -> None:
        raise RuntimeError(query.marker)

    host.contribs.provide(_DummyQuery, boom)
    try:
        # collect() logs "query.provider_failed" (log.exception) → the processor enqueues it.
        await host.contribs.collect(_DummyQuery(marker))  # must not raise: log-and-skip
    finally:
        host.contribs._providers[_DummyQuery].remove(boom)

    await CaptureDrain(0).tick()
    issue = await _issue_titled(marker)
    assert issue is not None, "the failing provider should have landed in issues"
    assert issue.status == IssueStatus.new
    assert issue.occurrence_count == 1


@pytest.mark.asyncio
async def test_a_failing_tracker_becomes_an_issue_of_its_own():
    """The reentrancy guard stops a tracker's *own* ordinary logging from feeding the queue back
    to itself — it must not also make a broken tracker invisible. Its exception is queued for the
    next tick and lands as an issue like any other."""
    marker = f"capture-test-{uuid.uuid4().hex}"
    tracker_failure = f"tracker itself is down {marker}"

    async def failing_tracker(_captured: ExceptionCaptured) -> None:
        raise RuntimeError(tracker_failure)

    capture.on_captured(failing_tracker)
    log = structlog.get_logger(_PROBE_LOGGER)
    try:
        try:
            raise ValueError(marker)
        except ValueError:
            log.exception("test.capture_probe")
        await CaptureDrain(0).tick()
        assert len(capture._QUEUE) == 1, "the tracker's own failure waits for the next tick"
    finally:
        capture._trackers.remove(failing_tracker)

    await CaptureDrain(0).tick()  # only the real tracker runs now

    # The original exception landed, and so did the tracker's own failure — each its own issue.
    assert await _issue_titled(marker) is not None
    assert await _issue_titled(tracker_failure) is not None


@pytest.mark.asyncio
async def test_occurrences_group_by_fingerprint_and_regress_after_resolve():
    marker = f"capture-test-{uuid.uuid4().hex}"

    async def record(version: str) -> Issue:
        async with db.admin_session_factory()() as session:
            seen = await see_occurrence(
                session,
                fingerprint=marker,
                title=f"ValueError: {marker}",
                version=version,
                context={},
            )
            await session.commit()
            return seen.issue

    await record("v1")
    issue = await record("v1")
    assert issue.occurrence_count == 2, "same fingerprint must fold into one issue"

    async with db.admin_session_factory()() as session:
        stored = await session.scalar(select(Issue).where(Issue.fingerprint == marker))
        assert stored is not None
        stored.status = IssueStatus.resolved
        stored.resolved_in_release = "v1"
        await session.commit()

    regressed = await record("v2")
    assert regressed.status == IssueStatus.regressed


@pytest.mark.asyncio
async def test_the_fact_that_opens_an_issue_points_back_at_the_request():
    """``_track`` runs on the drain's task, minutes after the request that failed and with none of
    its context — so the fact it records had no request id at all, and the one filter an admin
    reaches for (correlate by request) showed the log line and the occurrence but never the
    "this issue just opened" that explains them."""
    marker = f"capture-test-{uuid.uuid4().hex}"
    request_id = uuid.uuid7()
    log = structlog.get_logger(_PROBE_LOGGER)
    with structlog.contextvars.bound_contextvars(
        request_id=str(request_id), request_name="GET /acme/todo", user_id=str(uuid.uuid7())
    ):
        try:
            raise ValueError(marker)
        except ValueError:
            log.exception("test.capture_probe")

    await CaptureDrain(0).tick()

    async with db.admin_session_factory()() as session:
        facts = list(
            await session.scalars(
                select(BusinessEventRecord).where(BusinessEventRecord.request_id == request_id)
            )
        )
    # No actor and no org, deliberately: the journal is RLS-readable by the user it names, so
    # attributing an internal issue to whoever tripped it would put it in *their* activity feed.
    assert [(f.kind, f.request_name, f.user_id, f.org_id) for f in facts] == [
        ("issues.opened", "GET /acme/todo", None, None)
    ]
