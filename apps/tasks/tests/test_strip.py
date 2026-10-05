"""The film strip's arithmetic (see :mod:`apps.tasks.domain.strip`): positions, widths, bands,
axis, labels."""

from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from apps.tasks.domain.strip import (
    axis_ticks,
    bucket_blocks,
    bucket_seconds,
    spell_cadence,
    spell_duration,
    spell_tally,
    tally_bar,
    topic_label,
)

_START = datetime(2026, 9, 2, 10, 0, tzinfo=UTC)
_END = _START + timedelta(minutes=100)  # a minute is a percent


def _at(minutes: int) -> datetime:
    return _START + timedelta(minutes=minutes)


def _blocks(strip) -> list[tuple[str, float, float]]:
    return [(s.kind, s.left, s.width) for s in strip.segments]


# Ticks on round times, never span ÷ n (08:12, 09:24).


def test_the_axis_lands_on_round_times_not_on_equal_divisions():
    """A six-hour window ticks on the hour, whatever the odd minute it happens to start at."""
    ticks = axis_ticks(_START.replace(hour=7, minute=3), _START.replace(hour=13, minute=3))

    assert [t.label for t in ticks] == ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00"]


def test_a_short_window_ticks_finer_rather_than_showing_one_label():
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
    ticks = axis_ticks(_START, _START + timedelta(days=2))

    assert ticks[0].label == "02 Sep 12:00"


# Runs are bucketed into slots, none dropped.


def test_the_bucket_is_never_finer_than_the_screen_can_draw():
    six_hours = bucket_seconds(_START, _START + timedelta(hours=6))
    a_week = bucket_seconds(_START, _START + timedelta(days=7))

    assert (six_hours, a_week) == (60, 1800)


def test_a_slot_holding_two_outcomes_draws_both():
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

    assert [b.caption for b in blocks] == [
        "10:10 UTC · 1 parked",
        "10:10 UTC · 4 failed tries",
        "10:10 UTC · 12 done",
    ]


# A block links to the Timeline over its slot.


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
    """The kind, under which the fact is recorded; the whole topic would miss it."""
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


# A topic reads as its consumer, the event below.


def test_a_consumer_topic_reads_as_the_consumer_over_the_event():
    label = topic_label("evt:organizations.created:todo_welcome")

    assert (label.name, label.kind) == ("todo_welcome", "organizations.created")


def test_a_topic_that_is_not_a_reaction_is_already_its_own_name():
    """A chore (``rate_limit.purge``) keeps its name, with no event below."""
    label = topic_label("rate_limit.purge")

    assert (label.name, label.kind) == ("rate_limit.purge", "")


# Durations in words, one speller for the footnote and the cadence.


def test_a_duration_is_spelled_in_the_largest_unit_it_divides_into():
    assert [spell_duration(s) for s in (60, 7200, 86400)] == ["1 min", "2 hours", "1 day"]


def test_a_duration_no_unit_divides_stays_in_seconds():
    assert spell_duration(90) == "90 seconds"


def test_a_cadence_drops_the_count_when_it_is_one():
    assert [spell_cadence(s) for s in (3600, 7200, None)] == ["every hour", "every 2 hours", ""]


# The lane's bar: shares, with a floor so a rare band stays visible.


def test_a_bar_gives_each_band_its_share():
    assert tally_bar({"done": 3, "parked": 1}) == [("parked", 25.0), ("done", 75.0)]


def test_a_single_failure_among_thousands_stays_visible():
    bar = dict(tally_bar({"done": 2000, "parked": 1}))

    assert bar["parked"] > 4


def test_a_bar_is_drawn_worst_first():
    ordered = [kind for kind, _ in tally_bar({"done": 1, "pending": 1, "parked": 1, "attempt": 1})]

    assert ordered == ["parked", "attempt", "pending", "done"]


def test_a_lane_the_window_caught_nothing_of_has_no_bar():
    assert tally_bar({}) == []


# The cadence adds the next due time: the hour drifts.


def test_a_cadence_says_when_it_next_comes_round():
    at = datetime(2026, 9, 3, 3, 12, tzinfo=UTC)

    assert spell_cadence(86400, at) == "every day · next 03:12"


def test_a_cadence_with_no_next_run_says_only_how_often():
    assert spell_cadence(86400) == "every day"


def test_a_tally_spells_the_numbers_the_bar_only_shapes():
    assert spell_tally({"done": 40, "parked": 2}) == "2 parked · 40 done"
