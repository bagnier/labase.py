"""Shared arrangement for the tests that exercise the live logging chain.

``setup_logging`` reconfigures structlog, the root logger and Python's exception hooks
process-wide, so a test that wants a real log line must both isolate its log sink and put
everything back afterwards — otherwise every later test inherits the reconfiguration.
"""

import logging
import sys
import threading
import warnings
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
import structlog

from apps.shared import clock
from apps.shared.config import get_technical_settings
from apps.shared.logs import sink
from apps.shared.logs.chain import setup_logging
from apps.shared.logs.models import LogLine
from apps.shared.logs.repository import _columns
from apps.shared.logs.sink import clear_log_sink

# Pinned so a test that reasons about the window has fixed ends. These tests are about the chain,
# not about retention.
_ANCHOR = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


@pytest.fixture
def log_chain(tmp_path, monkeypatch) -> Iterator[Callable[[], list[LogLine]]]:
    """A pristine chain; yields what it produced, in the shape a reader receives.

    Reads the *queue* rather than the store: these tests ask what the chain wrote — a level, a
    name, a traceback that survived — and the trip through Postgres is neither what they are about
    nor available to them (no loop, no session). ``apps/shared/tests/test_log_repository`` owns
    that trip. The fallback dir is still redirected because the file writer and
    ``clear_log_sink`` touch it.
    """
    settings = get_technical_settings()
    monkeypatch.setattr(settings, "firehose_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(sink, "get_technical_settings", lambda: settings)
    monkeypatch.setattr(clock, "now", lambda: _ANCHOR)
    saved_config = structlog.get_config()
    saved_hooks = (threading.excepthook, sys.excepthook, sys.unraisablehook)
    saved_showwarning = warnings.showwarning
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    clear_log_sink()
    setup_logging()

    def written() -> list[LogLine]:
        """Newest first, like every read of the store — the queue fills oldest first."""
        lines = [LogLine(**_columns(one, "test")) for one in sink._drain_queue()]
        return list(reversed(lines))

    yield written

    clear_log_sink()
    structlog.configure(**saved_config)
    threading.excepthook, sys.excepthook, sys.unraisablehook = saved_hooks
    logging.captureWarnings(capture=False)
    warnings.showwarning = saved_showwarning
    root.handlers, root.level = saved_handlers, saved_level
