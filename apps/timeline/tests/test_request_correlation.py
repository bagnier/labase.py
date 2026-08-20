"""The promise, end to end: one failed request leaves records in all three sources, all naming it.

Every other test here seeds a source by hand — a firehose line written with the ids already on it,
an occurrence inserted with a context. That is what let the correlation keys go missing in
production while the suite stayed green: nothing drove a *real* request through the real chain and
asked whether the records it leaves behind actually name the same request.

So this one does. A handler raises; what follows is production wiring the whole way — the request
middleware, Starlette's 500 handler, the capture seam, the drain that folds the exception into an
issue and records the fact of its opening — and the assertion is the console's own read: filter the
timeline by that request id and get everything back.
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
from apps.shared.config import get_technical_settings
from apps.shared.contract import integration as shared_integration
from apps.shared.host import Host
from apps.shared.observability import capture, sink
from apps.shared.observability.capture import CaptureDrain
from apps.shared.observability.sink import LogDrain
from apps.shared.persistence import database as db
from apps.timeline.domain.models import TimelineSource
from apps.timeline.infra.repository import TimelineFilter

_NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
_ORG_ID, _USER_ID = str(uuid.uuid7()), str(uuid.uuid7())
_ISSUE_TITLE = "RuntimeError: the handler gave up"


@pytest.fixture(autouse=True)
def _a_private_chain(tmp_path, monkeypatch):
    """``setup_logging`` reconfigures structlog, the root logger and the exception hooks
    process-wide, so this puts everything back — the same care ``apps/shared/tests/conftest``
    takes, needed here because the whole point is to run the real chain."""
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
    """Drop the issue afterwards, so each run really *opens* one.

    A fingerprint is the exception type plus the frames — never the message, on purpose, so a
    unique message would not buy a fresh issue. Left behind, the second run folds into the first
    and records no ``issues.opened`` at all, which is precisely the fact under test.

    Torn down after the reader's own session (autouse fixtures are set up first and finalised
    last), so it opens — and disposes — an engine of its own. Raw SQL because the ``issues``
    tables are private to that context and the import-linter contract forbids reaching for its
    models — the same reason ``tests/e2e/seed_data`` writes them by hand.

    The caches are cleared on the way *in* as well as out, which is what makes this test
    order-independent. ``admin_session_factory`` is lru_cached and its pool binds to whichever
    loop first asked for one: any driver-based test running before this one leaves a pool bound
    to a dead loop, and the capture drain then fails to write its occurrence — silently, because
    the drain isolates its trackers by design. The symptom was this test's ``issue`` entry simply
    missing, three fixtures away from the cause.
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
    """Serve one request that raises, through the real middleware stack, and return its id.

    The stack is assembled by the shared context's own ``mount`` rather than listed here, so the
    test cannot drift from what production wires. The lifespan is deliberately not entered —
    these are the request-path pieces, not the background workers.
    """

    async def scope_the_request() -> None:
        # Stands in for auth's ``get_current_user`` and organizations' ``get_current_org``, which
        # bind exactly these while the request is served — below the middleware that reports it.
        structlog.contextvars.bind_contextvars(user_id=_USER_ID, org_id=_ORG_ID)

    host = Host()
    shared_integration.mount(host)
    host.app.get("/acme/explode", dependencies=[Depends(scope_the_request)])(_explode)

    response = TestClient(host.app, raise_server_exceptions=False).get("/acme/explode")

    assert response.status_code == 500
    await LogDrain(interval_seconds=0).tick()  # the lines reach the store, off the request path
    await CaptureDrain(0).tick()  # the exception becomes an occurrence, and a fact
    yield response.headers["X-Request-ID"]


async def _explode() -> None:
    raise RuntimeError("the handler gave up")


@pytest.mark.asyncio
async def test_one_failed_request_leaves_four_entries_that_all_name_it(failing_request, reader):
    """The four keys the console correlates on, asserted where an admin actually reads them.

    A set, not a list: the four records are stamped by three different clocks — structlog's for
    the lines, ``clock.now()`` for the occurrence, Postgres' ``now()`` for the fact — so their
    relative order is an accident of the test's pinned clock, not a promise. Two log lines and
    not one, because they say different things: *here is the exception*, then *the exchange
    ended with a 500*.
    """
    entries = await reader.search(TimelineFilter(request_id=failing_request))

    assert {(e.source, e.level, e.name, e.request_id) for e in entries} == {
        (TimelineSource.business, "info", "issues.opened", failing_request),
        (TimelineSource.issue, "error", "RuntimeError: the handler gave up", failing_request),
        (TimelineSource.logs, "error", "request.unhandled_error", failing_request),
        (TimelineSource.logs, "error", "request.finished", failing_request),
    }


@pytest.mark.asyncio
async def test_the_trace_and_the_occurrence_name_the_user_and_the_org(failing_request, reader):
    """Bound below the middleware that writes the finished line, and read by the seam that
    captures the exception — the two places they used to go missing."""
    entries = await reader.search(TimelineFilter(request_id=failing_request))

    assert {(e.source, e.user_id, e.org_id) for e in entries} == {
        # The fact stays server-wide: naming a user would file an internal issue in their feed.
        (TimelineSource.business, None, None),
        (TimelineSource.issue, _USER_ID, _ORG_ID),
        (TimelineSource.logs, _USER_ID, _ORG_ID),
    }
