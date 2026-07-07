"""Tiny text helpers for dashboard overview cards."""


def pluralize(n: int, word: str) -> str:
    return word if n == 1 else f"{word}s"


def overview_from_count(n: int, word: str, empty: str) -> list[str]:
    """One count-line for a dashboard ``Overview`` card — ``"3 decks"``, or the empty label."""
    return [f"{n} {pluralize(n, word)}"] if n else [empty]
