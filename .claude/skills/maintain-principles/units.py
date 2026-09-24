"""The units maintain-principles audits, and the claims of ``tests/meta/claims.py`` they carry.

A unit is each ``###`` principle of AGENTS.md, plus the section around any claim that falls
outside them, in README.md — marked ``[claims only]``, since only its claims are under audit. The
registry is read as syntax, never imported: importing it loads every holder test, and with them the
apps, which reach for the database.

Run from the repo root. ``python3 <this file>`` prints the numbered units, one line each;
``python3 <this file> NN`` prints unit ``NN``'s document, lines, scope and claims, for its audit
agent.
"""

import ast
import re
import sys
from pathlib import Path

DOCUMENTS = ("AGENTS.md", "README.md")
LINES = {document: Path(document).read_text().splitlines() for document in DOCUMENTS}
REGISTRY = ast.parse(Path("tests/meta/claims.py").read_text())


def normalised(source: str) -> str:
    return " ".join(source.split())


def headings(document: str) -> list[tuple[int, int, str]]:
    """(line, level, title) of every heading of ``document`` outside a fenced block."""
    found, fenced = [], False
    for number, line in enumerate(LINES[document], 1):
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and (match := re.match(r"(#+) (.*)", line)):
            found.append((number, len(match[1]), match[2]))
    return found


HEADINGS = {document: headings(document) for document in DOCUMENTS}


def is_unit(document: str, index: int) -> bool:
    return document == "AGENTS.md" and HEADINGS[document][index][1] == 3


def section_of(document: str, line: int) -> int:
    return max(i for i, (start, _, _) in enumerate(HEADINGS[document]) if start <= line)


WORDS = {
    document: [(number, word) for number, line in enumerate(lines, 1) for word in line.split()]
    for document, lines in LINES.items()
}
FLAT = {document: " ".join(word for _, word in words) for document, words in WORDS.items()}


def place_of(quote: str) -> tuple[str, int]:
    """The document and line a quote starts on — quotes are whitespace-normalised and may span
    lines, and each lives in exactly one document (``test_claims`` holds that)."""
    document = next(d for d in DOCUMENTS if normalised(quote) in FLAT[d])
    offset = FLAT[document][: FLAT[document].index(normalised(quote))].count(" ")
    return document, WORDS[document][offset][0]


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

carried: dict[tuple[str, int], list[str]] = {}
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
    document, line = place_of(quote)
    carried.setdefault((document, section_of(document, line)), []).append(entry)

UNITS = sorted(
    {(d, i) for d in DOCUMENTS for i in range(len(HEADINGS[d])) if is_unit(d, i)}
    | carried.keys(),
    key=lambda unit: (DOCUMENTS.index(unit[0]), unit[1]),
)


def unit(number: int) -> tuple[str, int, int, int]:
    """(document, heading index, start line, end line) of the unit numbered ``number``, from 1."""
    document, index = UNITS[number - 1]
    found = HEADINGS[document]
    start = found[index][0]
    end = found[index + 1][0] - 1 if index + 1 < len(found) else len(LINES[document])
    return document, index, start, end


if len(sys.argv) > 1:
    document, index, start, end = unit(int(sys.argv[1]))
    scope = "section" if is_unit(document, index) else "claims only"
    sys.stdout.write(f"{document} lines {start}-{end} · scope: {scope}\n")
    for entry in carried.get((document, index), []):
        sys.stdout.write(f"- {entry}\n")
else:
    for number in range(1, len(UNITS) + 1):
        document, index, start, end = unit(number)
        _, level, title = HEADINGS[document][index]
        scope = "" if is_unit(document, index) else " [claims only]"
        claims = len(carried.get((document, index), []))
        sys.stdout.write(
            f"{number:02} {document} {start}-{end} {'#' * level} {title}{scope} · {claims} claims\n"
        )
