"""The README and AGENTS.md, read as data — the documents the rest of this package asserts against.

Kept apart from :mod:`tests.meta.claims` so a test module can quote them without importing the
registry that points back at it.
"""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
README = _ROOT / "README.md"
AGENTS = _ROOT / "AGENTS.md"
DOCUMENTS = (README, AGENTS)


def text() -> str:
    return README.read_text()


def stated(document: Path) -> str:
    """What ``document`` states in its own words: the README's links into AGENTS.md are a mirror of
    its headings, held to them by ``test_docs``, not a second statement of them."""
    return "\n".join(
        line for line in document.read_text().splitlines() if "](AGENTS.md#" not in line
    )


def normalised(source: str) -> str:
    """Collapse every run of whitespace, so a quote may span the README's wrapped lines."""
    return " ".join(source.split())


def diagram_containing(needle: str) -> str:
    """The fenced block holding ``needle`` — the documents draw their chains as ASCII, and a
    drawing is a claim like any other. Raises if no single block matches, so a reworded diagram
    fails here rather than silently matching nothing."""
    blocks = [
        block
        for document in DOCUMENTS
        for block in re.findall(r"```.*?\n(.*?)```", document.read_text(), re.DOTALL)
        if needle in block
    ]
    if len(blocks) != 1:
        raise AssertionError(f"{len(blocks)} diagrams contain {needle!r}, expected 1")
    return blocks[0]
