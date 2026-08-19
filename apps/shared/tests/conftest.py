"""Shared arrangement for the tests that exercise the live logging chain.

``setup_logging`` reconfigures structlog, the root logger and Python's exception hooks
process-wide, so a test that wants a real log line must both isolate its firehose and put
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
from apps.shared.observability import firehose
from apps.shared.observability.firehose import (
    FirehoseWriter,
    LogLine,
    clear_firehose,
    read_firehose,
)
from apps.shared.observability.logging import setup_logging

# Pinned in the past so the firehose's two-day read window can never exclude a line written at
# the real clock: these tests are about the chain, not about retention.
_WINDOW_FLOOR_ANCHOR = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


@pytest.fixture
def log_chain(tmp_path, monkeypatch) -> Iterator[Callable[[], list[LogLine]]]:
    """A private firehose and a pristine chain; yields the firehose's own round trip.

    Calling the yielded reader ticks the writer once and reads the lines back — what the
    timeline would see for the lines the test just caused.
    """
    settings = get_technical_settings()
    monkeypatch.setattr(settings, "firehose_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(firehose, "get_technical_settings", lambda: settings)
    monkeypatch.setattr(clock, "now", lambda: _WINDOW_FLOOR_ANCHOR)
    saved_config = structlog.get_config()
    saved_hooks = (threading.excepthook, sys.excepthook, sys.unraisablehook)
    saved_showwarning = warnings.showwarning
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    clear_firehose()
    setup_logging()

    def drained() -> list[LogLine]:
        FirehoseWriter(interval_seconds=0).tick()
        return read_firehose()

    yield drained

    clear_firehose()
    structlog.configure(**saved_config)
    threading.excepthook, sys.excepthook, sys.unraisablehook = saved_hooks
    logging.captureWarnings(capture=False)
    warnings.showwarning = saved_showwarning
    root.handlers, root.level = saved_handlers, saved_level
