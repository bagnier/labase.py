"""End to end: one failing request, through production wiring, leaves records in all three
sources, and filtering the Timeline by its id returns them all. Other tests seed sources by hand.
"""

import logging
import sys
import threading
import uuid
import warnings
from datetime import UTC, datetime

import pytest
import pytest_asyncio
import structlog
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import text

import apps.main  # noqa: F401 — mounts every context, so issues subscribes its tracker
from apps.shared import clock
from apps.shared.contract import integration as shared_integration
from apps.shared.integration.host import Host
from apps.shared.logs import capture, sink
from apps.shared.logs.capture import CaptureDrain
from apps.shared.logs.sink import LogDrain
from apps.shared.persistence import database as db
from apps.shared.settings.env import get_technical_settings
from apps.timeline.domain.models import TimelineSource
from apps.timeline.infra.repository import TimelineFilter

_NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
_ORG_ID, _USER_ID = str(uuid.uuid7()), str(uuid.uuid7())
_ISSUE_TITLE = "RuntimeError: the handler gave up"


@pytest.fixture(autouse=True)
def _a_private_chain(tmp_path, monkeypatch):
    """The real chain, put back afterwards (as ``apps/shared/tests/conftest``)."""
    settings = get_technical_settings()
    monkeypatch.setattr(settings, "firehose_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(sink, "get_technical_settings", lambda: settings)
    monkeypatch.setattr(clock, "now", lambda: _NOW)
    saved_config = structlog.get_config()
    saved_hooks = (threading.excepthook, sys.excepthook, sys.unraisablehook)
    saved_showwarning = warnings.showwarning
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    sink.clear_log_sink()
    capture._QUEUE.clear()

    yield

    sink.clear_log_sink()
    capture._QUEUE.clear()
    structlog.configure(**saved_config)
    threading.excepthook, sys.excepthook, sys.unraisablehook = saved_hooks
    logging.captureWarnings(capture=False)
    warnings.showwarning = saved_showwarning
    root.handlers, root.level = saved_handlers, saved_level


def _clear_engine_caches() -> None:
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest_asyncio.fixture(autouse=True)
async def _forget_the_issue_this_test_opens():
    """Delete the issue afterwards, so each run opens one (the message is not part of the
    fingerprint). Raw SQL: the issues models are private to their context.

    Engine caches are cleared on the way in too: a pool bound to a dead loop would make the drain
    fail silently, isolating its tracker.
    """
    _clear_engine_caches()
    yield
    async with db.admin_session_factory()() as session:
        await session.execute(
            text("DELETE FROM issues WHERE title = :title"), {"title": _ISSUE_TITLE}
        )
        await session.commit()
    await db._admin_engine().dispose()
    _clear_engine_caches()


@pytest_asyncio.fixture
async def failing_request():
    """Serve one failing request through the stack ``mount`` builds, without the lifespan;
    return its id."""

    async def scope_the_request() -> None:
        # Binds what auth's and organizations' dependencies would.
        structlog.contextvars.bind_contextvars(user_id=_USER_ID, org_id=_ORG_ID)

    host = Host()
    shared_integration.mount(host)
    host.app.get("/acme/explode", dependencies=[Depends(scope_the_request)])(_explode)

    response = TestClient(host.app, raise_server_exceptions=False).get("/acme/explode")

    assert response.status_code == 500
    await LogDrain(interval_seconds=0).tick()
    await CaptureDrain(0).tick()
    yield response.headers["X-Request-ID"]


async def _explode() -> None:
    raise RuntimeError("the handler gave up")


@pytest.mark.asyncio
async def test_one_failed_request_leaves_four_entries_that_all_name_it(failing_request, reader):
    """A set: three clocks stamp the four records, so their order means nothing."""
    entries = await reader.search(TimelineFilter(request_id=failing_request))

    assert {(e.source, e.level, e.name, e.request_id) for e in entries} == {
        (TimelineSource.business, "info", "issues.opened", failing_request),
        (TimelineSource.issue, "error", "RuntimeError: the handler gave up", failing_request),
        (TimelineSource.logs, "error", "request.unhandled_error", failing_request),
        (TimelineSource.logs, "error", "request.finished", failing_request),
    }


@pytest.mark.asyncio
async def test_the_trace_and_the_occurrence_name_the_user_and_the_org(failing_request, reader):
    entries = await reader.search(TimelineFilter(request_id=failing_request))

    assert {(e.source, e.user_id, e.org_id) for e in entries} == {
        # Server-wide: naming the user would put an internal issue in their feed.
        (TimelineSource.business, None, None),
        (TimelineSource.issue, _USER_ID, _ORG_ID),
        (TimelineSource.logs, _USER_ID, _ORG_ID),
    }
