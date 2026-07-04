def pluralize(n: int, word: str) -> str:
    return word if n == 1 else f"{word}s"


def overview_from_count(n: int, word: str, empty: str) -> list[str]:
    return [f"{n} {pluralize(n, word)}"] if n else [empty]
