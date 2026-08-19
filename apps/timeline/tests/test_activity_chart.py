"""The activity graph draws the timeline's sources — all of them.

The chart reads the per-bucket counts by source key, so a source renamed on one side and not
the other leaves a series silently stuck at zero: the bars vanish and nothing fails, because
the e2e drivers assert on the raw activity dict and never on the rendered series.
"""

from datetime import UTC, datetime

from apps.timeline.domain.models import TimelineSource
from apps.timeline.infra.router import _activity_chart

_DAY = "2026-06-26"
_NOW = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)


def test_every_source_gets_its_own_series_with_its_own_counts():
    activity = {_DAY: {source.value: n for n, source in enumerate(TimelineSource, start=1)}}
    chart = _activity_chart(activity, "day", _NOW)
    drawn = {s["name"]: max(s["data"]) for s in chart["series"]}
    assert drawn == {"Logs": 1, "Business": 2, "Issue": 3}
