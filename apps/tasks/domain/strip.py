"""Tasks laid out as a film strip over a time window: what happened, where the list screen shows
what is owed.

The queue keeps one row per task, so the blocks come from the log sink's ``queue.task_retrying``
and ``queue.task_failed`` lines, joined on ``task_id``. The sink is bounded by retention, so an old
task may show fewer blocks than it had; the screen says so.

A block is an execution, never the wait before one: a recurring row is enqueued as the previous
one ends, and drawing the wait would paint a solid bar where a missed hour should show. A task
that never ran is drawn where it is due.

Widths are percentages computed here, where an off-by-one is tested, not in the template.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode

# Minimum block width, in percent: a task that parked within a second must stay visible.
_MIN_WIDTH = 0.4


def _reaction_parts(topic: str) -> tuple[str, str] | None:
    """``(kind, consumer)`` for a reaction's ``evt:<kind>:<consumer>`` topic, else ``None``."""
    parts = topic.split(":")
    return (parts[1], parts[2]) if len(parts) == 3 and parts[0] == "evt" else None


@dataclass(frozen=True)
class TopicLabel:
    """A topic's two display lines: the consumer, then its event (empty for a chore)."""

    name: str
    kind: str


def topic_label(topic: str) -> TopicLabel:
    """The consumer first, as it is what differs between topics; the event below it tells apart
    two consumers of the same name. Both stay visible: a column is not read through tooltips."""
    reaction = _reaction_parts(topic)
    return TopicLabel(name=reaction[1], kind=reaction[0]) if reaction else TopicLabel(topic, "")


@dataclass(frozen=True)
class StripSegment:
    """One block. ``kind`` is a band of ``BANDS``: ``attempt`` for a failed try followed by
    another, else where the slot left the task."""

    kind: str
    left: float
    width: float
    # Every state in the slot gets an equal band, worst on top: one park among a hundred runs
    # would be a pixel high in proportion.
    top: float
    height: float
    starts_at: datetime
    ends_at: datetime
    # The Timeline over this slot.
    href: str = ""
    # Rendered as ``title`` and ``aria-label``: the block is too narrow for text.
    caption: str = ""


@dataclass(frozen=True)
class StripLane:
    """One line of the strip: a task, or a whole recurring topic, whose rows form one heartbeat
    where a skipped hour shows."""

    topic: str
    label: TopicLabel
    # A recurring topic's cadence, sharing the second line with ``label.kind``: never both.
    cadence: str
    state: str
    # Per band, the counts in the window: a share would hide one park among two thousand runs.
    counts: dict[str, int]
    segments: list[StripSegment]


@dataclass(frozen=True)
class AxisTick:
    left: float
    label: str


# Round steps for the axis, so ticks read 08:00 rather than 08:12.
_STEPS = (
    60,
    120,
    300,
    600,
    900,
    1800,  # 1, 2, 5, 10, 15, 30 minutes
    3600,
    7200,
    10800,
    21600,
    43200,  # 1, 2, 3, 6, 12 hours
    86400,
    172800,
    604800,  # 1, 2, 7 days
)
_MAX_TICKS = 8


def axis_ticks(window_start: datetime, window_end: datetime) -> list[AxisTick]:
    """Axis ticks on round instants; past a day, labels include the day."""
    span = (window_end - window_start).total_seconds()
    if span <= 0:
        return []
    step = next((s for s in _STEPS if span / s <= _MAX_TICKS), _STEPS[-1])
    fmt = "%d %b %H:%M" if span > 86400 else "%H:%M"

    ticks = []
    at = _ceil_to(window_start, step)
    while at <= window_end:
        ticks.append(
            AxisTick(
                left=round((at - window_start).total_seconds() / span * 100, 3),
                label=at.strftime(fmt),
            )
        )
        at += timedelta(seconds=step)
    return ticks


def _ceil_to(moment: datetime, step: int) -> datetime:
    """The first multiple of ``step`` at or after ``moment``, on the clock, not the window."""
    epoch = moment.timestamp()
    return moment + timedelta(seconds=(-epoch) % step)


# Columns per lane: a lane is about 900px, and finer blocks would be invisible.
_MAX_BUCKETS = 400


def bucket_seconds(window_start: datetime, window_end: datetime) -> int:
    """The time slot one block covers: runs are bucketed, none dropped, since a morning can hold
    ten thousand."""
    span = (window_end - window_start).total_seconds()
    return next((s for s in _STEPS if span / s <= _MAX_BUCKETS), _STEPS[-1])


# Bucket width and cadence are worded here alike.
_UNITS = (("day", 86400), ("hour", 3600), ("min", 60))


def _whole_unit(seconds: int) -> tuple[int, str]:
    """The largest unit dividing ``seconds`` exactly: ``(2, "hour")`` for 7200."""
    for unit, size in _UNITS:
        if seconds >= size and seconds % size == 0:
            return seconds // size, unit
    return seconds, "second"


def spell_duration(seconds: int) -> str:
    """``"2 hours"``, ``"1 min"``."""
    count, unit = _whole_unit(seconds)
    return f"{count} {unit}" if count == 1 else f"{count} {unit}s"


def spell_cadence(seconds: int | None, next_run: datetime | None = None) -> str:
    """``"every hour"``, ``"every 2 hours"``, or ``""``; with ``next_run``, the next due time,
    as the hour drifts (see ``queue.RecurringTopic``)."""
    if not seconds:
        return ""
    count, unit = _whole_unit(seconds)
    every = f"every {unit}" if count == 1 else f"every {count} {unit}s"
    return f"{every} · next {next_run:%H:%M}" if next_run else every


# Worst first: stacking order, block wording and legend. A new band needs a colour
# (``test_surfaces``).
BANDS = (
    ("parked", "parked"),
    ("attempt", "failed tries"),
    ("retrying", "retrying"),
    ("pending", "pending"),
    ("done", "done"),
)
_BAND_ORDER = tuple(kind for kind, _ in BANDS)
_BAND_WORDS = dict(BANDS)


# A band's minimum share of the bar, in percent, so a rare park stays visible; the exact counts
# are written beside it.
_MIN_SHARE = 6.0


def spell_tally(counts: Mapping[str, int]) -> str:
    """``"40 done · 2 parked"``."""
    return " · ".join(f"{counts[kind]} {word}" for kind, word in BANDS if counts.get(kind))


def tally_bar(counts: Mapping[str, int]) -> list[tuple[str, float]]:
    """``(kind, width%)`` per band, worst first, summing to 100; empty when nothing ran."""
    present = [(kind, counts[kind]) for kind in _BAND_ORDER if counts.get(kind)]
    if not present:
        return []
    total = sum(n for _, n in present)
    floored = [(kind, max(n / total * 100, _MIN_SHARE)) for kind, n in present]
    scale = 100 / sum(width for _, width in floored)
    return [(kind, round(width * scale, 3)) for kind, width in floored]


_TIMELINE = "/console/timeline"


def _timeline_link(topic: str, slot_start: datetime, slot_end: datetime) -> str:
    """The Timeline over this slot, searching the event kind: the whole topic would miss the
    facts, recorded under the kind."""
    reaction = _reaction_parts(topic)
    query = {
        "q": reaction[0] if reaction else topic,
        "from_dt": slot_start.strftime("%Y-%m-%dT%H:%M:%S"),
        "to_dt": slot_end.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return f"{_TIMELINE}?{urlencode(query)}"


def bucket_blocks(
    *,
    slot_start: datetime,
    slot_end: datetime,
    topic: str,
    counts: dict[str, int],
    attempts: int,
    window_start: datetime,
    window_end: datetime,
) -> list[StripSegment]:
    """One slot, one equal band per state that landed in it."""
    span = (window_end - window_start).total_seconds()
    held = {**{k: v for k, v in counts.items() if v}, **({"attempt": attempts} if attempts else {})}
    present = [state for state in _BAND_ORDER if held.get(state)]
    if not present:
        return []
    share = 100 / len(present)
    href = _timeline_link(topic, slot_start, slot_end)
    left = (slot_start - window_start).total_seconds() / span * 100
    width = (slot_end - slot_start).total_seconds() / span * 100
    return [
        StripSegment(
            kind=state,
            left=round(left, 3),
            width=round(max(width, _MIN_WIDTH), 3),
            top=round(index * share, 3),
            height=round(share, 3),
            starts_at=slot_start,
            ends_at=slot_end,
            caption=f"{slot_start.strftime('%H:%M')} UTC · {held[state]} {_BAND_WORDS[state]}",
            href=href,
        )
        for index, state in enumerate(present)
    ]
