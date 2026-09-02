"""Laying one task out as a film strip: where its blocks start, how wide, what colour.

The queue records a task once, not once per try — ``locked_at`` is only the last claim, and
``_complete`` clears it — so the blocks come from the *log*: ``queue.task_retrying`` writes one
line per failed try, ``queue.task_failed`` one at the park. The history is therefore honest about
its own provenance: it shows what was recorded, and the sink is best-effort and bounded by its
retention, so an old task can show fewer blocks than it really had.

**What a block is, and what it is not.** A block is an *execution*, never the idle wait before
one. Drawing the wait would be defensible for a one-shot and ruinous for a recurring topic, whose
next row is enqueued the moment the last one finishes: an hourly purge would be a solid bar across
the window instead of the six ticks that let a reader spot the hour it went missing. So a task
that ran once is a tick at the moment it ended, and a task that retried is one block per interval
between tries — the sawtooth the backoff actually makes.

The arithmetic is pure — a window and a handful of instants in, percentages out — so it is settled
here rather than inside a template where an off-by-one reads as a rendering quirk.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from apps.console.domain.queue_strip import axis_ticks, bucket_blocks, bucket_seconds

_START = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
_END = _START + timedelta(minutes=100)  # 100 minutes, so a minute is a percent


def _at(minutes: int) -> datetime:
    return _START + timedelta(minutes=minutes)


def _blocks(strip) -> list[tuple[str, float, float]]:
    return [(s.kind, s.left, s.width) for s in strip.segments]


# The axis is read by someone matching a block against the clock in their head, so its labels have
# to be times a person thinks in. Splitting the window into equal parts gives 08:12 and 09:24 —
# arithmetically right, useless to read against.


def test_the_axis_lands_on_round_times_not_on_equal_divisions():
    """A six-hour window ticks on the hour, whatever the odd minute it happens to start at."""
    ticks = axis_ticks(_START.replace(hour=7, minute=3), _START.replace(hour=13, minute=3))

    assert [t.label for t in ticks] == ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00"]


def test_a_short_window_ticks_finer_rather_than_showing_one_label():
    """The step comes off a ladder of durations a clock has names for — never span ÷ n."""
    ticks = axis_ticks(_START, _START + timedelta(minutes=30))

    assert [t.label for t in ticks] == [
        "10:00",
        "10:05",
        "10:10",
        "10:15",
        "10:20",
        "10:25",
        "10:30",
    ]


def test_a_tick_sits_where_its_time_falls_in_the_window():
    """Two hours ticks every quarter, and the third quarter sits a quarter of the way across."""
    ticks = axis_ticks(_START, _START + timedelta(hours=2))

    assert [(t.label, t.left) for t in ticks][2] == ("10:30", 25.0)


def test_a_window_spanning_days_says_which_day():
    """``14:00`` twice in a column is a label that has stopped identifying anything."""
    ticks = axis_ticks(_START, _START + timedelta(days=2))

    assert ticks[0].label == "02 Sep 12:00"


# Drawing one block per run does not survive a real instance: a morning of sign-ups is ten thousand
# runs, and a cap that keeps four hundred of them is a screen that says "everything went fine"
# about the 96% it dropped. Buckets keep every run — the block becomes a slot of time on a lane,
# carrying how many landed in it and the worst thing that happened there.


def test_the_bucket_is_never_finer_than_the_screen_can_draw():
    """A block thinner than a couple of pixels is a block nobody sees, so the window picks the
    finest duration that still fits in a bounded number of columns."""
    six_hours = bucket_seconds(_START, _START + timedelta(hours=6))
    a_week = bucket_seconds(_START, _START + timedelta(days=7))

    assert (six_hours, a_week) == (60, 1800)


def test_a_slot_holding_two_outcomes_draws_both():
    """Collapsing a minute to its worst colour loses the count, and collapsing it to its commonest
    loses the park. A slot is split by state instead: every band is a fact, none is a summary."""
    blocks = bucket_blocks(
        slot_start=_at(10),
        slot_end=_at(11),
        topic="test.bucket",
        counts={"done": 3, "parked": 1},
        attempts=0,
        window_start=_START,
        window_end=_END,
    )

    assert [(b.kind, b.top, b.height) for b in blocks] == [
        ("parked", 0.0, 50.0),
        ("done", 50.0, 50.0),
    ]


def test_the_worst_band_sits_on_top_and_never_thins_to_nothing():
    """One park among a hundred clean runs is the row an admin is looking for; proportional bands
    would draw it one pixel high. Every state present takes an equal share."""
    blocks = bucket_blocks(
        slot_start=_at(10),
        slot_end=_at(11),
        topic="test.bucket",
        counts={"done": 100, "parked": 1},
        attempts=0,
        window_start=_START,
        window_end=_END,
    )

    assert (blocks[0].kind, blocks[0].height) == ("parked", 50.0)


def test_failed_tries_are_a_band_of_their_own():
    """A retry writes a log line, not a queue row: the tries are their own band, so a slot can say
    "it ran clean twice and failed three times" without one hiding the other."""
    blocks = bucket_blocks(
        slot_start=_at(10),
        slot_end=_at(11),
        topic="test.bucket",
        counts={"done": 2},
        attempts=3,
        window_start=_START,
        window_end=_END,
    )

    assert [b.kind for b in blocks] == ["attempt", "done"]


def test_a_slot_says_what_each_of_its_bands_holds():
    blocks = bucket_blocks(
        slot_start=_at(10),
        slot_end=_at(11),
        topic="test.bucket",
        counts={"done": 12, "parked": 1},
        attempts=4,
        window_start=_START,
        window_end=_END,
    )

    assert [b.label for b in blocks] == [
        "10:10 UTC · 1 parked",
        "10:10 UTC · 4 failed tries",
        "10:10 UTC · 12 done",
    ]


# A block knows what happened and when, which is exactly the pair the Timeline asks for. Clicking
# one should land on the same moment, already narrowed — otherwise a reader who spots a red slot
# has to retype its minute into another screen by hand.


def test_a_block_links_to_the_timeline_over_its_own_slot():
    blocks = bucket_blocks(
        slot_start=_at(10),
        slot_end=_at(11),
        topic="evt:auth.user_created:create_personal_org",
        counts={"parked": 1},
        attempts=0,
        window_start=_START,
        window_end=_END,
    )
    link = urlparse(blocks[0].href)

    assert (link.path, parse_qs(link.query)) == (
        "/console/timeline",
        {
            "q": ["auth.user_created"],
            "from_dt": ["2026-09-02T10:10:00"],
            "to_dt": ["2026-09-02T10:11:00"],
        },
    )


def test_the_link_searches_the_event_kind_rather_than_the_whole_topic():
    """A queue topic is ``evt:<kind>:<consumer>`` (see ``events.wiring``), and only the kind in the
    middle is a word the Timeline's other two sources know: the journal records the fact under it,
    and the retry lines carry it inside their topic. Searching the whole topic would find the log
    lines and miss every fact."""
    blocks = bucket_blocks(
        slot_start=_at(10),
        slot_end=_at(11),
        topic="rate_limit.purge",
        counts={"done": 1},
        attempts=0,
        window_start=_START,
        window_end=_END,
    )

    assert parse_qs(urlparse(blocks[0].href).query)["q"] == ["rate_limit.purge"]
