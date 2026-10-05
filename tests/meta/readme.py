"""The README and AGENTS.md as data, apart from :mod:`tests.meta.claims`, which imports tests."""

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
README = _ROOT / "README.md"
AGENTS = _ROOT / "AGENTS.md"
DOCUMENTS = (README, AGENTS)


def text() -> str:
    return README.read_text()


def stated(document: Path) -> str:
    """``document`` without the README's links to AGENTS.md headings, which state nothing."""
    return "\n".join(
        line for line in document.read_text().splitlines() if "](AGENTS.md#" not in line
    )


def normalised(source: str) -> str:
    """Whitespace collapsed, so a quote may span wrapped lines."""
    return " ".join(source.split())


def diagram_containing(needle: str) -> str:
    """The one fenced block holding ``needle``; raises unless exactly one does."""
    blocks = [
        block
        for document in DOCUMENTS
        for block in re.findall(r"```.*?\n(.*?)```", document.read_text(), re.DOTALL)
        if needle in block
    ]
    if len(blocks) != 1:
        raise AssertionError(f"{len(blocks)} diagrams contain {needle!r}, expected 1")
    return blocks[0]
