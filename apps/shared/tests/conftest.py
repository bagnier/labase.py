"""The live logging chain for a test: ``setup_logging`` reconfigures the process, so it is put
back afterwards."""

import logging
import sys
import threading
import warnings
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
import structlog

from apps.shared import clock
from apps.shared.logs import sink
from apps.shared.logs.chain import setup_logging
from apps.shared.logs.models import LogLine
from apps.shared.logs.repository import _columns
from apps.shared.logs.sink import clear_log_sink
from apps.shared.settings.env import get_technical_settings

# Fixed window ends; retention is not under test here.
_ANCHOR = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


@pytest.fixture
def log_chain(tmp_path, monkeypatch) -> Iterator[Callable[[], list[LogLine]]]:
    """A pristine chain; yields a reader of what it wrote, from the queue, not the store
    (``test_log_repository`` covers the store)."""
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
        """Newest first, like the store."""
        lines = [LogLine(**_columns(one, "test")) for one in sink._drain_queue()]
        return list(reversed(lines))

    yield written

    clear_log_sink()
    structlog.configure(**saved_config)
    threading.excepthook, sys.excepthook, sys.unraisablehook = saved_hooks
    logging.captureWarnings(capture=False)
    warnings.showwarning = saved_showwarning
    root.handlers, root.level = saved_handlers, saved_level
