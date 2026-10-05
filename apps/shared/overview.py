"""The count lines of an ``Overview`` card, spelled alike by every app."""

RECENT_ITEMS = 3
"""How many items an ``Overview`` card's "recent" list shows."""


def pluralize(n: int, word: str) -> str:
    return word if n == 1 else f"{word}s"


def overview_from_count(n: int, word: str, empty: str) -> list[str]:
    """``["3 decks"]``, or ``[empty]``."""
    return [f"{n} {pluralize(n, word)}"] if n else [empty]
