"""The README, read as data — the one document the rest of this package asserts against.

Kept apart from :mod:`tests.meta.claims` so a test module can quote the README without importing
the registry that points back at it.
"""

import re
from pathlib import Path

README = Path(__file__).resolve().parents[2] / "README.md"


def text() -> str:
    return README.read_text()


def normalised(source: str) -> str:
    """Collapse every run of whitespace, so a quote may span the README's wrapped lines."""
    return " ".join(source.split())


def diagram_containing(needle: str) -> str:
    """The fenced block holding ``needle`` — the README draws its chains as ASCII, and a drawing
    is a claim like any other. Raises if no single block matches, so a reworded diagram fails
    here rather than silently matching nothing."""
    blocks = [
        block for block in re.findall(r"```.*?\n(.*?)```", text(), re.DOTALL) if needle in block
    ]
    if len(blocks) != 1:
        raise AssertionError(f"{len(blocks)} README diagrams contain {needle!r}, expected 1")
    return blocks[0]
