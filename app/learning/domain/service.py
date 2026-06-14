"""Pure spaced-repetition domain logic — no framework or persistence imports."""

from datetime import date, timedelta

from app.learning.domain.models import CardResource, DueCard, Outcome, Schedule

# Interval (in days) until the next review, indexed by the card's resulting level.
# Follows the Fibonacci sequence; the level is capped at MAX_LEVEL.
FIBONACCI_INTERVALS = {1: 1, 2: 1, 3: 2, 4: 3, 5: 5, 6: 8, 7: 13, 8: 21, 9: 34}
MAX_LEVEL = 9


def interval_for_level(level: int) -> int:
    return FIBONACCI_INTERVALS[level]


def apply_outcome(current_level: int, today: date, outcome: Outcome) -> Schedule:
    """Compute the new schedule after marking a card.

    "learned" promotes one level (capped); "again" resets to level 1. The next
    review is always computed from `today` (the effective answer day), never from
    the previously scheduled date — so late reviews never compound.
    """
    new_level = 1 if outcome is Outcome.again else min(current_level + 1, MAX_LEVEL)
    return Schedule(
        level=new_level,
        last_reviewed_on=today,
        next_review_on=today + timedelta(days=interval_for_level(new_level)),
    )


def is_due(next_review_on: date | None, today: date) -> bool:
    """A card is due when never studied (no schedule) or its next review has arrived."""
    return next_review_on is None or next_review_on <= today


def order_due_cards(cards: list[DueCard]) -> list[DueCard]:
    """Never-studied cards first (in deck/card order), then studied cards by oldest
    next review, ties broken by deck order then card order."""
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
    """The cards to present in a session today: those due, in review order."""
    return order_due_cards([c for c in cards if is_due(c.next_review_on, today)])


def needs_resources(level: int) -> bool:
    """A card still needs help resources while not yet retained (level 0 or 1)."""
    return level <= 1


def compute_resources(cards: list[CardResource]) -> list[tuple[str, str]]:
    """Group help resources by deck (deck order), deck link first then card links.

    Within a deck: skip empty links, skip a card link equal to the deck link, and
    deduplicate. Returns a flat list of (deck_name, resource_url) in display order.
    """
    decks_in_order = [d for _, d in sorted({(c.deck_position, c.deck) for c in cards})]
    result: list[tuple[str, str]] = []
    for deck in decks_in_order:
        deck_cards = sorted((c for c in cards if c.deck == deck), key=lambda c: c.card_position)
        deck_resource = next((c.deck_resource for c in deck_cards), None)
        seen: list[str] = []
        if deck_resource:
            seen.append(deck_resource)
            result.append((deck, deck_resource))
        for c in deck_cards:
            link = c.card_resource
            if link and link != deck_resource and link not in seen:
                seen.append(link)
                result.append((deck, link))
    return result
