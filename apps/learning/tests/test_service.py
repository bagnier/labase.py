import uuid
from datetime import date

import pytest

from apps.learning.domain.exceptions import DailyLimitReached
from apps.learning.domain.models import CardResource, DueCard, Outcome
from apps.learning.domain.service import (
    apply_outcome,
    compute_resources,
    is_due,
    needs_resources,
    order_due_cards,
    review_card,
    select_due_cards,
)

TODAY = date(2024, 9, 1)


@pytest.mark.parametrize(
    ("initial_level", "new_level", "interval"),
    [
        (1, 2, 1),
        (2, 3, 2),
        (3, 4, 3),
        (4, 5, 5),
        (5, 6, 8),
        (6, 7, 13),
        (7, 8, 21),
        (8, 9, 34),
        (9, 9, 34),
    ],
)
def test_learned_follows_fibonacci(initial_level, new_level, interval):
    s = apply_outcome(initial_level, TODAY, Outcome.learned)
    assert s.level == new_level
    assert s.last_reviewed_on == TODAY
    assert (s.next_review_on - TODAY).days == interval


def test_first_interval_is_one_day():
    s = apply_outcome(0, TODAY, Outcome.learned)
    assert s.level == 1
    assert (s.next_review_on - TODAY).days == 1


def test_again_resets_to_level_one():
    s = apply_outcome(4, TODAY, Outcome.again)
    assert s.level == 1
    assert s.last_reviewed_on == TODAY
    assert (s.next_review_on - TODAY).days == 1


def test_is_due():
    assert is_due(None, TODAY) is True
    assert is_due(date(2024, 8, 30), TODAY) is True
    assert is_due(TODAY, TODAY) is True
    assert is_due(date(2024, 9, 2), TODAY) is False


def test_order_unstudied_first_then_oldest_next_review():
    cards = [
        DueCard("PY001", 1, 0, 0, date(2024, 7, 15)),
        DueCard("PY002", 2, 0, 1, date(2024, 7, 15)),
        DueCard("PY005", 0, 0, 4, None),
        DueCard("PYA02", 2, 1, 1, date(2024, 7, 15)),
    ]
    ordered = [c.external_id for c in order_due_cards(cards)]
    # unstudied first, then by next_review, ties by deck then card position
    assert ordered == ["PY005", "PY001", "PY002", "PYA02"]


def test_select_due_cards_filters_then_orders():
    cards = [
        DueCard("PY001", 3, 0, 0, date(2024, 9, 5)),  # not due (future)
        DueCard("PY002", 0, 0, 1, None),  # unstudied → due, first
        DueCard("PY003", 2, 0, 2, date(2024, 8, 20)),  # due
    ]
    assert [c.external_id for c in select_due_cards(cards, TODAY)] == ["PY002", "PY003"]


def test_needs_resources_threshold():
    assert needs_resources(0) is True
    assert needs_resources(1) is True
    assert needs_resources(2) is False
    assert needs_resources(9) is False


def test_resources_dedup_and_skip_deck_equal_and_empty():
    deck_url = "deck-url"
    cards = [
        CardResource("débuter Python", 0, 0, deck_url, "intro"),
        CardResource("débuter Python", 0, 1, deck_url, "controlflow"),
        CardResource("débuter Python", 0, 2, deck_url, "intro"),  # dup
        CardResource("débuter Python", 0, 3, deck_url, deck_url),  # equal to deck
        CardResource("débuter Python", 0, 4, deck_url, None),  # empty
    ]
    assert compute_resources(cards) == [
        ("débuter Python", deck_url),
        ("débuter Python", "intro"),
        ("débuter Python", "controlflow"),
    ]


def test_resources_grouped_by_deck_in_order():
    cards = [
        CardResource("débuter Python", 0, 0, "d1", "c1"),
        CardResource("Python avancé", 1, 0, "d2", "c2"),
    ]
    assert compute_resources(cards) == [
        ("débuter Python", "d1"),
        ("débuter Python", "c1"),
        ("Python avancé", "d2"),
        ("Python avancé", "c2"),
    ]


# ── review_card (orchestration through the ReviewRepositoryProtocol port) ─────

CARD_ID = uuid.uuid7()


class _FakeReviewRepo:
    """In-memory port double: state per card + a canned daily count."""

    def __init__(self, state=None, reviews_today=0):
        self._state = state
        self._reviews_today = reviews_today
        self.applied = []

    async def get_state(self, card_id):
        return self._state

    async def reviews_today(self, today):
        return self._reviews_today

    async def apply_schedule(self, card_id, schedule):
        self.applied.append((card_id, schedule))


class _State:
    def __init__(self, level, last_reviewed_on=None):
        self.level = level
        self.last_reviewed_on = last_reviewed_on


@pytest.mark.asyncio
async def test_review_card_schedules_from_current_level():
    repo = _FakeReviewRepo(state=_State(level=2))
    schedule = await review_card(repo, CARD_ID, Outcome.learned, TODAY, daily_limit=10)
    assert schedule.level == 3
    assert repo.applied == [(CARD_ID, schedule)]


@pytest.mark.asyncio
async def test_review_card_treats_unstudied_card_as_level_zero():
    repo = _FakeReviewRepo(state=None)
    schedule = await review_card(repo, CARD_ID, Outcome.learned, TODAY, daily_limit=10)
    assert schedule.level == 1


@pytest.mark.asyncio
async def test_review_card_enforces_daily_limit():
    repo = _FakeReviewRepo(state=None, reviews_today=3)
    with pytest.raises(DailyLimitReached):
        await review_card(repo, CARD_ID, Outcome.learned, TODAY, daily_limit=3)
    assert repo.applied == []


@pytest.mark.asyncio
async def test_review_card_allows_remarking_a_card_already_reviewed_today():
    repo = _FakeReviewRepo(state=_State(level=2, last_reviewed_on=TODAY), reviews_today=3)
    schedule = await review_card(repo, CARD_ID, Outcome.again, TODAY, daily_limit=3)
    assert schedule.level == 1
    assert len(repo.applied) == 1
