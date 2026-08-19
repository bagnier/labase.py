"""Reading the firehose back: the window floor, the filters, and the newest-first cut.

The writer's side lives in ``test_firehose.py``. This one pins what ``read_firehose`` promises
a caller — the unified timeline is its only production reader, and it reaches every filter
here through kwargs, so a guard that silently stops matching would surface as an empty screen.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from apps.shared import clock
from apps.shared.config import get_technical_settings
from apps.shared.observability import firehose
from apps.shared.observability.firehose import (
    append_firehose,
    clear_firehose,
    firehose_dir,
    read_firehose,
)

# Pinned so the window (now - FIREHOSE_WINDOW, i.e. two days) has fixed ends: its floor is
# 2026-07-10 12:00, which every timestamp below is chosen to sit above or under on purpose.
_NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
_INSIDE = "2026-07-12T10:00:00"
_JUST_UNDER_THE_FLOOR = "2026-07-10T09:00:00"  # same day as the floor, three hours too early
_A_DAY_THE_WINDOW_DROPS = "2026-07-08T10:00:00"


@pytest.fixture(autouse=True)
def _isolate_firehose(tmp_path, monkeypatch):
    settings = get_technical_settings()
    monkeypatch.setattr(settings, "firehose_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(firehose, "get_technical_settings", lambda: settings)
    monkeypatch.setattr(clock, "now", lambda: _NOW)
    clear_firehose()
    yield
    clear_firehose()


def _seed(event: str, ts: str = _INSIDE, **fields: object) -> None:
    append_firehose({"timestamp": ts, "level": "info", "event": event, **fields})


def _names(lines) -> list[str]:
    return [line.name for line in lines]


def _append_raw(day_file: Path, text: str) -> None:
    """Straight to the day file: no healthy writer emits a blank or truncated line on demand."""
    day_file.write_text(day_file.read_text(encoding="utf-8") + text, encoding="utf-8")


def test_reads_every_line_newest_first():
    _seed("a.one", ts="2026-07-12T10:00:00")
    _seed("b.two", ts="2026-07-12T11:00:00")
    found = read_firehose()
    assert _names(found) == ["b.two", "a.one"]


def test_keeps_only_lines_at_the_named_level():
    _seed("kept", level="error")
    _seed("dropped", level="info")
    found = read_firehose(level="error")
    assert _names(found) == ["kept"]


def test_matches_the_level_whatever_the_case():
    _seed("kept", level="ERROR")
    found = read_firehose(level="error")
    assert _names(found) == ["kept"]


def test_keeps_only_lines_of_the_named_org():
    _seed("kept", org_id="org-1")
    _seed("dropped", org_id="org-2")
    found = read_firehose(org_id="org-1")
    assert _names(found) == ["kept"]


def test_keeps_only_lines_of_the_named_user():
    _seed("kept", user_id="user-1")
    _seed("dropped", user_id="user-2")
    found = read_firehose(user_id="user-1")
    assert _names(found) == ["kept"]


def test_keeps_only_lines_of_the_named_request():
    _seed("kept", request_id="req-1")
    _seed("dropped", request_id="req-2")
    found = read_firehose(request_id="req-1")
    assert _names(found) == ["kept"]


def test_text_searches_the_whole_line_not_just_its_name():
    _seed("kept", detail="a needle in the payload")
    _seed("dropped", detail="nothing of the sort")
    found = read_firehose(text="needle")
    assert _names(found) == ["kept"]


def test_matches_the_text_whatever_the_case():
    _seed("kept", detail="A Needle")
    found = read_firehose(text="needle")
    assert _names(found) == ["kept"]


def test_drops_what_falls_under_the_window_floor():
    _seed("kept")
    _seed("dropped", ts=_JUST_UNDER_THE_FLOOR)
    found = read_firehose()
    assert _names(found) == ["kept"]


def test_a_wider_window_reaches_further_back():
    _seed("kept", ts=_A_DAY_THE_WINDOW_DROPS)
    found = read_firehose(window=timedelta(days=5))
    assert _names(found) == ["kept"]


def test_from_dt_tightens_the_floor():
    _seed("kept", ts="2026-07-12T11:00:00")
    _seed("dropped", ts="2026-07-12T10:00:00")
    found = read_firehose(from_dt=datetime(2026, 7, 12, 10, 30, tzinfo=UTC))
    assert _names(found) == ["kept"]


def test_from_dt_cannot_reach_further_back_than_the_window():
    """The window floor is the firehose's retention horizon; ``from_dt`` may only tighten it."""
    _seed("dropped", ts=_JUST_UNDER_THE_FLOOR)
    found = read_firehose(from_dt=datetime(2026, 7, 1, tzinfo=UTC))
    assert _names(found) == []


def test_to_dt_caps_the_newest_end():
    _seed("kept", ts="2026-07-12T10:00:00")
    _seed("dropped", ts="2026-07-12T11:00:00")
    found = read_firehose(to_dt=datetime(2026, 7, 12, 10, 30, tzinfo=UTC))
    assert _names(found) == ["kept"]


def test_limit_keeps_the_newest_of_what_matched():
    _seed("oldest", ts="2026-07-12T09:00:00")
    _seed("middle", ts="2026-07-12T10:00:00")
    _seed("newest", ts="2026-07-12T11:00:00")
    found = read_firehose(limit=2)
    assert _names(found) == ["newest", "middle"]


def test_skips_a_line_the_writer_left_unparsable():
    """A truncated line — a process killed mid-write — must not blind the reader to the rest."""
    _seed("kept")
    day_file = firehose_dir() / "firehose-2026-07-12.jsonl"
    _append_raw(day_file, '{"event": "trunc\n')
    found = read_firehose()
    assert _names(found) == ["kept"]


def test_ignores_the_blank_lines_between_records():
    _seed("kept")
    day_file = firehose_dir() / "firehose-2026-07-12.jsonl"
    _append_raw(day_file, "\n\n")
    found = read_firehose()
    assert _names(found) == ["kept"]


def test_promotes_the_reserved_keys_and_leaves_the_rest_in_the_payload():
    _seed("shape", org_id="org-1", user_id="user-1", request_id="req-1", detail="extra")
    found = read_firehose()
    assert (found[0].org_id, found[0].user_id, found[0].request_id, found[0].payload) == (
        "org-1",
        "user-1",
        "req-1",
        {"detail": "extra"},
    )


def test_an_empty_filter_value_filters_nothing():
    """The timeline builds these from URL query params, where an untouched field arrives as ""."""
    _seed("kept", level="info", org_id="org-1")
    found = read_firehose(level="", org_id="", user_id="", request_id="", text="")
    assert _names(found) == ["kept"]
