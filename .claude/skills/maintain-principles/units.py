"""The units maintain-principles audits, and the claims of ``tests/meta/claims.py`` they carry.

A unit is each ``###`` under ``## Principles`` and each ``####`` of README.md, plus the section
around any claim that falls outside them — marked ``[claims only]``, since only its claims are
under audit. The registry is read as syntax, never imported: importing it loads every holder
test, and with them the apps, which reach for the database.

Run from the repo root. ``python3 <this file>`` prints the numbered units, one line each;
``python3 <this file> NN`` prints unit ``NN``'s lines, scope and claims, for its audit agent.
"""

import ast
import re
import sys
from pathlib import Path

README = Path("README.md").read_text().splitlines()
REGISTRY = ast.parse(Path("tests/meta/claims.py").read_text())


def normalised(source: str) -> str:
    return " ".join(source.split())


def headings() -> list[tuple[int, int, str]]:
    """(line, level, title) of every heading outside a fenced block."""
    found, fenced = [], False
    for number, line in enumerate(README, 1):
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and (match := re.match(r"(#+) (.*)", line)):
            found.append((number, len(match[1]), match[2]))
    return found


HEADINGS = headings()


def is_unit(index: int) -> bool:
    _, level, _ = HEADINGS[index]
    parent = next((title for _, lvl, title in reversed(HEADINGS[:index]) if lvl == 2), "")
    return level == 4 or (level == 3 and parent == "Principles")


def section_of(line: int) -> int:
    return max(i for i, (start, _, _) in enumerate(HEADINGS) if start <= line)


WORDS = [(number, word) for number, line in enumerate(README, 1) for word in line.split()]
FLAT = " ".join(word for _, word in WORDS)


def line_of(quote: str) -> int:
    """The README line a quote starts on — quotes are whitespace-normalised and may span lines."""
    return WORDS[FLAT[: FLAT.index(normalised(quote))].count(" ")][0]


MODULE_OF = {
    alias.name: node.module
    for node in REGISTRY.body
    if isinstance(node, ast.ImportFrom)
    for alias in node.names
}
CLAIMS = next(
    node.value.elts
    for node in REGISTRY.body
    if isinstance(node, ast.Assign)
    and isinstance(node.value, ast.List)
    and ast.unparse(node.targets[0]) == "CLAIMS"
)

carried: dict[int, list[str]] = {}
for call in CLAIMS:
    match call:
        case ast.Call(
            func=ast.Name(id="held"),
            args=[ast.Constant(value=str(name)), ast.Constant(value=str(quote)), *holders],
        ):
            tests = (f"{MODULE_OF[h.id]}.{h.id}" for h in holders if isinstance(h, ast.Name))
            backing = "held by " + ", ".join(tests)
        case ast.Call(
            func=ast.Name(id="waived"),
            args=[
                ast.Constant(value=str(name)),
                ast.Constant(value=str(quote)),
                ast.Constant(value=str(reason)),
            ],
        ):
            backing = f"waived: {reason}"
        case _:
            raise ValueError(f"not a held() or waived() claim: {ast.unparse(call)}")
    entry = f'{name} — "{normalised(quote)}" — {backing}'
    carried.setdefault(section_of(line_of(quote)), []).append(entry)

UNITS = sorted({i for i in range(len(HEADINGS)) if is_unit(i)} | carried.keys())


def unit(number: int) -> tuple[int, int, int]:
    """(heading index, start line, end line) of the unit numbered ``number``, from 1."""
    index = UNITS[number - 1]
    start = HEADINGS[index][0]
    end = HEADINGS[index + 1][0] - 1 if index + 1 < len(HEADINGS) else len(README)
    return index, start, end


if len(sys.argv) > 1:
    index, start, end = unit(int(sys.argv[1]))
    scope = "section" if is_unit(index) else "claims only"
    sys.stdout.write(f"README.md lines {start}-{end} · scope: {scope}\n")
    for entry in carried.get(index, []):
        sys.stdout.write(f"- {entry}\n")
else:
    for number in range(1, len(UNITS) + 1):
        index, start, end = unit(number)
        _, level, title = HEADINGS[index]
        scope = "" if is_unit(index) else " [claims only]"
        claims = len(carried.get(index, []))
        sys.stdout.write(
            f"{number:02} {start}-{end} {'#' * level} {title}{scope} · {claims} claims\n"
        )
