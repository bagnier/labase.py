"""The count lines an ``Overview`` card shows, spelled the same way by every app.

A dashboard or console card answers "how much of this is there?" in one or two short lines, and
every app that contributes one reaches here rather than formatting its own — so ``1 deck`` and
``3 decks`` never diverge between two cards on the same page. Nothing more general lives here:
these are card lines, not string utilities.
"""


def pluralize(n: int, word: str) -> str:
    return word if n == 1 else f"{word}s"


def overview_from_count(n: int, word: str, empty: str) -> list[str]:
    """One count-line for a dashboard ``Overview`` card — ``"3 decks"``, or the empty label."""
    return [f"{n} {pluralize(n, word)}"] if n else [empty]
