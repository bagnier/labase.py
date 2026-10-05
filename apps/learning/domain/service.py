"""Spaced repetition; the review reaches persistence through `ReviewRepositoryProtocol`."""

import uuid
from datetime import date, timedelta

from apps.learning.domain.exceptions import DailyLimitReached
from apps.learning.domain.models import CardResource, DueCard, Outcome, Schedule
from apps.learning.domain.repository import ReviewRepositoryProtocol

# Days to the next review by level (Fibonacci), up to :data:`MAX_LEVEL`.
FIBONACCI_INTERVALS = {1: 1, 2: 1, 3: 2, 4: 3, 5: 5, 6: 8, 7: 13, 8: 21, 9: 34}
MAX_LEVEL = 9


def interval_for_level(level: int) -> int:
    return FIBONACCI_INTERVALS[level]


def apply_outcome(current_level: int, today: date, outcome: Outcome) -> Schedule:
    """ "learned" moves up a level, "again" back to 1. The next review counts from `today`, not
    the scheduled date, so lateness never compounds."""
    new_level = 1 if outcome is Outcome.again else min(current_level + 1, MAX_LEVEL)
    return Schedule(
        level=new_level,
        last_reviewed_on=today,
        next_review_on=today + timedelta(days=interval_for_level(new_level)),
    )


async def review_card(
    repo: ReviewRepositoryProtocol,
    card_id: uuid.UUID,
    outcome: Outcome,
    today: date,
    daily_limit: int,
) -> Schedule:
    """Mark a card under the daily cap of distinct cards (re-marking is free), and store its
    schedule."""
    state = await repo.get_state(card_id)
    already_today = state is not None and state.last_reviewed_on == today
    if not already_today and await repo.reviews_today(today) >= daily_limit:
        raise DailyLimitReached
    schedule = apply_outcome(state.level if state else 0, today, outcome)
    await repo.apply_schedule(card_id, schedule)
    return schedule


def is_due(next_review_on: date | None, today: date) -> bool:
    return next_review_on is None or next_review_on <= today


def order_due_cards(cards: list[DueCard]) -> list[DueCard]:
    """Never-studied cards first, then by oldest next review; ties by deck, then card order."""
    return sorted(
        cards,
        key=lambda c: (
            c.next_review_on is not None,
            c.next_review_on or date.min,
            c.deck_position,
            c.card_position,
        ),
    )


def select_due_cards(cards: list[DueCard], today: date) -> list[DueCard]:
    return order_due_cards([c for c in cards if is_due(c.next_review_on, today)])


def needs_resources(level: int) -> bool:
    """Level 0 or 1."""
    return level <= 1


def compute_resources(cards: list[CardResource]) -> list[tuple[str, str]]:
    """``(deck_name, url)`` in deck order, the deck link before its cards'; empty, repeated or
    deck-equal card links skipped."""
    decks_in_order = [d for _, d in sorted({(c.deck_position, c.deck) for c in cards})]
    result: list[tuple[str, str]] = []
    for deck in decks_in_order:
        deck_cards = sorted((c for c in cards if c.deck == deck), key=lambda c: c.card_position)
        deck_resource_url = next((c.deck_resource_url for c in deck_cards), None)
        seen: list[str] = []
        if deck_resource_url:
            seen.append(deck_resource_url)
            result.append((deck, deck_resource_url))
        for c in deck_cards:
            link = c.card_resource_url
            if link and link != deck_resource_url and link not in seen:
                seen.append(link)
                result.append((deck, link))
    return result
