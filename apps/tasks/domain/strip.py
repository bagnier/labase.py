"""One task, laid out as a film strip across a time window.

The list screen answers *what is owed now*; this answers *what happened*. The queue itself cannot
tell the second story on its own — it keeps one row per task, whose ``attempts`` is a bare counter
and whose ``locked_at`` ``_complete`` clears on the way out — so the blocks come from the log sink,
where every failed try already writes its own line (``queue.task_retrying``, then
``queue.task_failed`` at the park). Nothing new is recorded for this screen; it reads what the seam
was already saying, joined on the ``task_id`` those lines carry.

That provenance is also the honest limit, and the screen says so: the sink is best-effort and
bounded by its own retention, so an old task can show fewer blocks than it really had. A ledger of
attempts would be a table of its own — a decision to take on its own merits, not a side effect of
wanting a picture.

**A block is an execution, never the wait before one.** That is the rule the whole reading rests
on. A recurring row is enqueued the instant the previous one finishes, so drawing enqueue → done
would paint an hourly topic as one solid bar across the window; drawing the runs alone makes it a
row of ticks, where the missing hour is the thing that jumps out. A task that has not run at all
is the one exception: it has no execution to show, so it is drawn where it is *due*.

Percentages rather than pixels, computed here rather than in the template: an off-by-one in a
width is a bug, and inside Jinja it reads as a rendering quirk nobody tests.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode

# A block thinner than this disappears, and a task that ran and parked inside one second is
# exactly the one an admin is looking for. Wide enough to see, narrow enough not to lie about
# duration at any sane window.
_MIN_WIDTH = 0.4


def _reaction_parts(topic: str) -> tuple[str, str] | None:
    """``(kind, consumer)`` if this topic addresses a durable consumer, else ``None``.

    A reaction is keyed ``evt:<kind>:<consumer>`` (``events.wiring``); a recurring chore is keyed by
    a plain name. Everything that reads a topic for a human reads it through here.
    """
    parts = topic.split(":")
    return (parts[1], parts[2]) if len(parts) == 3 and parts[0] == "evt" else None


@dataclass(frozen=True)
class TopicLabel:
    """A topic split across the two lines a name gets: the consumer, and the event under it.

    ``kind`` is empty for a topic that is nobody's reaction — a recurring chore has no event
    behind it, and a second line repeating the first teaches nothing.
    """

    name: str
    kind: str


def topic_label(topic: str) -> TopicLabel:
    """A queue topic, unstacked over two lines.

    A topic is addressing, and addressing is repetitive on purpose: every reaction opens with the
    same ``evt:`` and the consumer — the only half that differs between two lines — comes last. So
    the consumer takes the line and the event it reacts to takes the dim one below.

    Both stay on screen rather than one hiding behind a hover: these are read as a *column*, and a
    column of names each holding half its meaning in a tooltip is a column nobody reads.

    Consumer names are unique per event, not globally (``wiring.add_consumer``), so two reactions
    to different events *could* shorten to the same word. The line below is what tells them apart,
    and the JSON face still carries the topic whole.
    """
    reaction = _reaction_parts(topic)
    return TopicLabel(name=reaction[1], kind=reaction[0]) if reaction else TopicLabel(topic, "")


@dataclass(frozen=True)
class StripSegment:
    """One block: where it sits in the window, and what it says.

    ``kind`` is the meaning, never the colour — ``attempt`` for a try that failed and was followed
    by another, then where the slot left the task: ``done``, ``parked``, ``retrying`` for one still
    owed after a failure, ``pending`` for one due but not yet run. The full vocabulary is ``BANDS``.
    """

    kind: str
    left: float
    width: float
    # A slot is shared: every state that landed in it takes a band, worst at the top. Equal
    # shares, never proportional — one park among a hundred clean runs is the row an admin is
    # looking for, and its true proportion would draw it a pixel high.
    top: float
    height: float
    starts_at: datetime
    ends_at: datetime
    # Where the block leads: the Timeline, over this very slot. A reader who spots a red minute
    # should not have to retype it into another screen.
    href: str = ""
    # What pointing at the block says. A block is a few pixels wide, so everything it knows has to
    # be reachable that way; built here and rendered as ``title`` + ``aria-label``, the shape the
    # activity heatmap already uses for its day cells.
    caption: str = ""


@dataclass(frozen=True)
class StripLane:
    """One line of the film strip, and what its left margin says about it.

    A lane is not always a task. A recurring topic re-enqueues a *new row* the instant the last one
    finishes, so an hourly purge is seven rows over six hours; seven lanes of one tick each say
    nothing, while one lane of seven ticks is a heartbeat, and the hour it skipped is the thing a
    reader is looking for. One-shots have no such family — their lane is the task itself.
    """

    topic: str
    label: TopicLabel
    # How often the lane comes round, for a recurring topic; empty for everything else. It shares
    # the line under the name with ``label.kind``, and never collides with it: a topic is either a
    # reaction to an event or a chore on a clock, never both.
    cadence: str
    state: str
    # What the window holds for this lane, per band — the composition its right margin shows.
    # Counts, never shares: one park among two thousand clean runs is the row this screen exists
    # for, and its true proportion of the bar would be half a pixel.
    counts: dict[str, int]
    segments: list[StripSegment]


@dataclass(frozen=True)
class AxisTick:
    left: float
    label: str


# Durations a clock has a name for. The axis picks the finest one that keeps the label count
# civil, so the ticks fall on times a reader recognises — splitting the window into equal parts
# is arithmetically right and unreadable, giving 08:12 and 09:24 on a six-hour view.
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
    """Where to write a time along the window, and what to write.

    Ticks land on round instants — the hour, the quarter, the day — rather than at even fractions
    of the span, because the axis is read by someone matching a block against the clock in their
    head. A window wider than a day says which day, since ``14:00`` appearing twice in one column
    has stopped identifying anything.
    """
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
    """The first round instant at or after ``moment`` — rounded against the clock, not the window,
    so two screens over different spans agree on where an hour falls."""
    epoch = moment.timestamp()
    return moment + timedelta(seconds=(-epoch) % step)


# How many columns a lane may hold. A block thinner than a couple of pixels is a block nobody
# sees, and a lane is around nine hundred pixels wide — so this is the point past which finer
# buckets buy nothing but DOM.
_MAX_BUCKETS = 400


def bucket_seconds(window_start: datetime, window_end: datetime) -> int:
    """How wide a slot of time one block covers, for this window.

    Drawing one block per run does not survive a real instance: a morning of sign-ups is ten
    thousand runs on a handful of lanes. Bucketing keeps every one of them — nothing is capped,
    nothing is dropped — and costs only the ability to point at a single run, which the backlog
    tab and the log sink both still answer.
    """
    span = (window_end - window_start).total_seconds()
    return next((s for s in _STEPS if span / s <= _MAX_BUCKETS), _STEPS[-1])


# Seconds are the queue's own unit; nothing on this screen is read in them. Both the bucket width
# and a recurring topic's cadence come through here, so the same duration is never worded two ways.
_UNITS = (("day", 86400), ("hour", 3600), ("min", 60))


def _whole_unit(seconds: int) -> tuple[int, str]:
    """The largest unit ``seconds`` divides into whole — ``(2, "hour")`` for 7200. Seconds
    themselves when none does, rather than a rounding a reader cannot see."""
    for unit, size in _UNITS:
        if seconds >= size and seconds % size == 0:
            return seconds // size, unit
    return seconds, "second"


def spell_duration(seconds: int) -> str:
    """How long something lasts: ``"2 hours"``, ``"1 min"``."""
    count, unit = _whole_unit(seconds)
    return f"{count} {unit}" if count == 1 else f"{count} {unit}s"


def spell_cadence(seconds: int | None, next_run: datetime | None = None) -> str:
    """How often something comes round: ``"every hour"``, ``"every 2 hours"``, ``""`` for a topic
    with no cadence at all. The count is dropped at one, which is how it is said.

    With ``next_run``, the due instant is appended — "every day" answers how often and nothing at
    all about when. It is written as *next*, not as an hour the chore keeps: the queue re-enqueues
    from the moment the last pass ended (``queue._complete``), so the hour drifts and a fixed one
    would be a schedule nothing honours.
    """
    if not seconds:
        return ""
    count, unit = _whole_unit(seconds)
    every = f"every {unit}" if count == 1 else f"every {count} {unit}s"
    return f"{every} · next {next_run:%H:%M}" if next_run else every


# Worst first: the order the bands stack in, and the order a reader scans for. One tuple, read
# three ways — the stacking order, the words a block says, and the legend under the strip. A band
# added here is a band the legend names and the stylesheet must colour (``test_surfaces``).
BANDS = (
    ("parked", "parked"),
    ("attempt", "failed tries"),
    ("retrying", "retrying"),
    ("pending", "pending"),
    ("done", "done"),
)
_BAND_ORDER = tuple(kind for kind, _ in BANDS)
_BAND_WORDS = dict(BANDS)


# The floor a band gets in a lane's bar, in percent. A bar is drawn to be read as area, and area
# is exactly what buries the interesting case: one park among two thousand clean runs is 0.05% of
# the row. Same trade as ``_MIN_WIDTH`` on the film itself — a share below this is widened, and the
# rest give up the difference, so the bar lies a little about proportion and not at all about
# presence. The exact counts are written beside it.
_MIN_SHARE = 6.0


def spell_tally(counts: Mapping[str, int]) -> str:
    """``"40 done · 2 parked"`` — the exact numbers the bar only shows the shape of."""
    return " · ".join(f"{counts[kind]} {word}" for kind, word in BANDS if counts.get(kind))


def tally_bar(counts: Mapping[str, int]) -> list[tuple[str, float]]:
    """``(kind, width%)`` per band the window holds for one lane, worst first, summing to 100.

    Empty for a lane the window caught nothing of — a recurring topic keeps its row whatever the
    window holds, and a full-width bar of nothing would read as a run that happened.
    """
    present = [(kind, counts[kind]) for kind in _BAND_ORDER if counts.get(kind)]
    if not present:
        return []
    total = sum(n for _, n in present)
    floored = [(kind, max(n / total * 100, _MIN_SHARE)) for kind, n in present]
    scale = 100 / sum(width for _, width in floored)
    return [(kind, round(width * scale, 3)) for kind, width in floored]


# The Timeline reads the same window from its own three sources; a block hands it the slot it
# covers and the word most likely to name what happened in it.
_TIMELINE = "/console/timeline"


def _timeline_link(topic: str, slot_start: datetime, slot_end: datetime) -> str:
    """The Timeline, narrowed to this slot and to what ran in it.

    The search term is the *event kind*, not the whole topic: only the kind in the middle is a word
    the Timeline's other sources know — the journal records the fact under it, and a retry line
    carries it inside its own topic. Searching the whole topic would find the log lines and miss
    every fact. A topic with no such shape searches for itself.
    """
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
    """One slot of a lane, split by what landed in it.

    Nothing is collapsed: a minute holding three clean runs and one park draws both, because
    either summary loses the half that matters — the worst colour hides the count, the commonest
    hides the park. The bands share the row equally rather than by count, for the same reason.
    """
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
