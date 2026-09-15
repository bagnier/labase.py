#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "rope @ git+https://github.com/python-rope/rope@d2c51277d772fb7e31153974d5cddbd6df1bd125",
# ]
# ///
"""One named refactoring over a Python project, computed by rope, verified for coverage.

Prints a unified diff and a coverage report; writes nothing unless --apply is given.
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import sys
import tempfile
import warnings
from pathlib import Path
from typing import NoReturn

SKIP_DIRS = {
    ".git", ".venv", "venv", ".tox", ".nox", "node_modules", "build", "dist",
    "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache", ".ropeproject",
    "site-packages", ".eggs",
}

DIFF_INLINE_LIMIT = 300  # lines; beyond this the diff goes to a file


def die(msg: str) -> NoReturn:
    sys.stdout.flush()  # keep the error after the report it belongs to
    print(f"error: {msg}", file=sys.stderr)
    raise SystemExit(2)


# --- rope, pinned ------------------------------------------------------------


def load_rope():
    """Import rope and refuse a build that predates PEP 695 support.

    rope reports VERSION == "1.14.0" on master too, so the version string cannot
    tell the pinned build from the PyPI release. The walker method can.
    """
    from rope.refactor import patchedast

    if not hasattr(patchedast._PatchingASTWalker, "_TypeAlias"):
        die(
            "rope is too old: no PEP 695 support (`type X = ...`, `class C[T]`).\n"
            "       This script pins a git SHA in its own header — run it with "
            "`uv run` and let uv resolve it."
        )


def py_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in filenames:
            if name.endswith(".py"):
                yield Path(dirpath) / name


def parse_python(text: str, path: Path | str) -> ast.Module:
    try:
        return ast.parse(text.lstrip("\ufeff"))  # rope keeps the BOM; ast refuses it
    except (SyntaxError, ValueError) as broken:
        die(f"{path} is not parsable Python: {broken}")


def unparsable(root: Path, folders: list[str]) -> list[Path]:
    """Files rope will choke on. It parses every module under its source folders."""
    bad: list[Path] = []
    for folder in folders:
        for path in py_files(root / folder if folder else root):
            try:
                ast.parse(path.read_bytes())  # bytes: honours the BOM and any coding cookie
            except (SyntaxError, ValueError):
                bad.append(path.relative_to(root))
    return sorted(set(bad))


def source_folders(root: Path) -> list[str]:
    """Top-level directories holding Python code, plus the root when it holds any.

    rope resolves cross-module references only inside its source folders. Left to
    its default it finds none in a `src/` layout and silently reports a rename as
    touching one file.
    """
    folders: list[str] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name in SKIP_DIRS or entry.name.startswith("."):
            continue
        if next(py_files(entry), None) is not None:
            folders.append(entry.name)
    if any(root.glob("*.py")):
        folders.append("")  # the project root itself; rope reads "." as something else
    return folders


def open_project(root: Path, import_style: str):
    from rope.base.prefs import ImportPrefs
    from rope.base.project import Project

    if not root.is_dir():
        die(f"--project {root} is not a directory")
    folders = source_folders(root)
    if not folders:
        die(f"no Python source folder found under {root}")

    blocked = unparsable(root, folders)
    if blocked:
        sys.stdout.flush()
        print("error: rope parses every module under its source folders, and these fail:",
              file=sys.stderr)
        for path in blocked:
            print(f"  {path}", file=sys.stderr)
        die(
            "fix them, or move them outside the source folders listed below.\n"
            f"       source folders: {', '.join(f or '.' for f in folders)}"
        )

    project = Project(
        str(root),
        ropefolder=None,  # never write a .ropeproject/ into the repo
        source_folders=folders,
        python_path=folders,
        imports=ImportPrefs(preferred_import_style=import_style),
    )
    return project, folders


def python_file(root: Path, given: str, flag: str) -> Path:
    """Validate a path the caller handed us, before rope turns it into something obscure."""
    path = Path(given)
    if not path.is_absolute():
        path = root / path
    if not path.exists():
        hint = (
            " — create it first (touch), rope only moves into a module that exists"
            if flag == "--to"
            else ""
        )
        die(f"{flag} {given}: no such file{hint}")
    if not path.is_file():
        die(f"{flag} {given} is a directory, not a Python file")
    if path.suffix != ".py":
        die(f"{flag} {given} is not a .py file")
    try:
        path.resolve().relative_to(root)
    except ValueError:
        die(f"{flag} {given} is outside the project ({root})")
    return path.resolve()


# --- locating a symbol without offsets ---------------------------------------


def name_offset(text: str, lineno: int, name: str) -> int:
    lines = text.splitlines(keepends=True)
    if not 1 <= lineno <= len(lines):
        die(f"--line {lineno} is outside the file, which has {len(lines)} lines")
    start = sum(len(line) for line in lines[: lineno - 1])
    hit = re.search(rf"\b{re.escape(name)}\b", lines[lineno - 1])
    if hit is None:
        die(f"{name!r} does not appear on line {lineno}")
    return start + hit.start()


def definition_lines(text: str, name: str, path: Path) -> list[int]:
    """Every line defining `name`: def, class, assignment, annotated assignment."""
    tree = parse_python(text, path)
    found: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                found.append(node.lineno)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    found.append(target.lineno)
        elif isinstance(node, (ast.AnnAssign, ast.TypeAlias)):
            target = getattr(node, "target", None) or getattr(node, "name", None)
            if isinstance(target, ast.Name) and target.id == name:
                found.append(target.lineno)
    return sorted(set(found))


def module_level_names(text: str, path: Path) -> set[str]:
    """Names bound directly in the module body — where a rename can shadow something."""
    names: set[str] = set()
    for node in parse_python(text, path).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
            names.add(node.name.id)
    return names


def is_local(text: str, lineno: int, path: Path) -> bool:
    """True when the line sits inside a function body — a symbol no other file can reach."""
    for node in ast.walk(parse_python(text, path)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            body_start = node.body[0].lineno
            if body_start <= lineno <= (node.end_lineno or body_start):
                return True
    return False


def locate(text: str, name: str, line: int | None, path: Path) -> tuple[int, int]:
    """Offset of the symbol's definition, and the line it sits on."""
    if line is not None:
        return name_offset(text, line, name), line
    lines = definition_lines(text, name, path)
    if not lines:
        die(f"no definition of {name!r} in this file — pass --line to point at one")
    if len(lines) > 1:
        die(f"{name!r} is defined on lines {lines} — pass --line to choose")
    return name_offset(text, lines[0], name), lines[0]


def line_span_offsets(text: str, first: int, last: int) -> tuple[int, int]:
    """Offsets covering lines `first`..`last`, indentation excluded, newline excluded."""
    lines = text.splitlines(keepends=True)
    if not 1 <= first <= last <= len(lines):
        die(
            f"--lines {first}-{last} is not a range inside a file of {len(lines)} lines "
            "(first line is 1, and first must not exceed last)"
        )
    start = sum(len(line) for line in lines[: first - 1])
    start += len(lines[first - 1]) - len(lines[first - 1].lstrip())
    end = sum(len(line) for line in lines[:last]) - (
        len(lines[last - 1]) - len(lines[last - 1].rstrip())
    )
    return start, end


# --- coverage ----------------------------------------------------------------


def coverage_report(
    root: Path, name: str, touched: set[Path], def_file: Path, imports_only: bool
) -> int:
    """Name every file that mentions `name` and that rope left alone. Returns exit advice.

    A module is only reachable from another file through an import, so matching its bare
    stem anywhere would flag every docstring that happens to use the word.
    """
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    missed: list[Path] = []
    for path in sorted(py_files(root)):
        if path.resolve() in touched:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = [line for line in text.splitlines() if "import" in line] if imports_only else [text]
        if any(pattern.search(line) for line in lines):
            missed.append(path.relative_to(root))

    where = "importing" if imports_only else "mentioning"
    if not missed:
        print(f"coverage: every file {where} {name!r} is in the change set.")
        return 0

    if touched == {def_file.resolve()}:
        print(
            f"\nSTOP — rope touched only {def_file.name}, yet {len(missed)} other file(s) "
            f"are {where} {name!r}:"
        )
        for path in missed:
            print(f"  {path}")
        print(
            "\nNothing was applied. Two causes look like this — tell them apart before forcing:\n"
            "  - the source folders above do not cover the whole project, so rope never saw\n"
            "    the importers. Fix the layout, rerun.\n"
            "  - every remaining reference is dynamic (a string, getattr, an entry point).\n"
            "    rope is right; add --force, then edit those call sites by hand."
        )
        return 1

    print(f"\ncoverage: {len(missed)} file(s) {where} {name!r} were not changed:")
    for path in missed:
        print(f"  {path}")
    print("Read each one: a homonym is expected, a real reference is a miss.")
    return 0


# --- output ------------------------------------------------------------------


def leftovers(changes, name: str) -> list[tuple[str, int, str]]:
    """The old name surviving inside a string literal of a file rope just rewrote.

    rope renames code, never text, so an `__all__` entry or a `getattr` key keeps the
    old name and breaks at import time. Same-name locals are left out: rope is right to
    leave those alone and there is nothing to decide about them.
    """
    import io
    import tokenize

    pattern = re.compile(rf"\b{re.escape(name)}\b")
    found: list[tuple[str, int, str]] = []
    for change in getattr(changes, "changes", []):
        contents = getattr(change, "new_contents", None)
        if contents is None:
            continue
        lines = contents.splitlines()
        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(contents).readline))
        except (tokenize.TokenError, IndentationError, SyntaxError):
            continue
        for token in tokens:
            if token.type != tokenize.STRING or not pattern.search(token.string):
                continue
            for number in range(token.start[0], token.end[0] + 1):
                line = lines[number - 1]
                if pattern.search(line):
                    found.append((change.resource.path, number, line.strip()))
    return found


def report(changes, root: Path, name: str, def_file: Path, operation: str, propagates: bool) -> int:
    touched = {Path(root, resource.path).resolve() for resource in changes.get_changed_resources()}
    print(f"{operation}: {len(touched)} file(s)")
    for path in sorted(touched):
        print(f"  {path.relative_to(root)}")

    description = changes.get_description()
    if description.count("\n") > DIFF_INLINE_LIMIT:
        handle, diff_path = tempfile.mkstemp(prefix=f"refactor-{operation}-", suffix=".diff")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(description)
        print(f"\ndiff ({description.count(chr(10))} lines) written to {diff_path}")
    else:
        print()
        print(description)

    surviving = leftovers(changes, name) if operation in {"rename", "move-symbol"} else []
    if surviving:
        print(f"\nleft behind: {name!r} survives in strings of the files rope rewrote:")
        for path, number, line in surviving[:10]:
            print(f"  {path}:{number}  {line[:86]}")
        if len(surviving) > 10:
            print(f"  ... and {len(surviving) - 10} more")
        print("An __all__ entry or a getattr key breaks at runtime; prose usually stays.")

    if not propagates:
        print("\ncoverage: not checked — this change cannot reach another file by construction.")
        return 0
    return coverage_report(root, name, touched, def_file, operation == "move-module")


# --- operations --------------------------------------------------------------


def build(args) -> tuple[object, object, Path, str, str, bool]:
    """Return (project, changes, definition file, symbol name, label, crosses-files)."""
    from rope.base import libutils
    from rope.refactor.extract import ExtractMethod, ExtractVariable
    from rope.refactor.inline import create_inline
    from rope.refactor.move import create_move
    from rope.refactor.rename import Rename

    root = Path(args.project).resolve()
    project, folders = open_project(root, args.import_style)
    print(f"project: {root}\nsource folders: {', '.join(f or '.' for f in folders)}")

    if args.command == "move-module":
        module = python_file(root, args.module, "--module")
        destination = Path(args.to) if Path(args.to).is_absolute() else root / args.to
        if not destination.is_dir():
            die(f"--to {args.to} is not an existing directory")
        if (destination / module.name).exists():
            die(
                f"{args.to}/{module.name} already exists — rope would edit that module "
                "instead of refusing. Rename one of the two first."
            )
        resource = libutils.path_to_resource(project, str(module))
        changes = create_move(project, resource).get_changes(
            libutils.path_to_resource(project, str(destination.resolve()))
        )
        return project, changes, module, module.stem, "move-module", True

    target = python_file(root, args.file, "--file")
    resource = libutils.path_to_resource(project, str(target))
    if resource is None:
        die(f"--file {args.file} is outside the project ({root})")
    text = resource.read()

    if args.command == "rename":
        if not args.to.isidentifier():
            die(f"--to {args.to!r} is not a Python identifier")
        if args.to == args.symbol:
            die(f"--to {args.to!r} is the name it already has")
        offset, line = locate(text, args.symbol, args.line, target)
        if not is_local(text, line, target) and args.to in module_level_names(text, target):
            die(
                f"{args.to!r} is already defined at module level in {target.name}; "
                "renaming onto it would shadow one of the two"
            )
        changes = Rename(project, resource, offset).get_changes(args.to, docs=args.docs)
        return project, changes, target, args.symbol, "rename", not is_local(text, line, target)

    if args.command == "inline":
        offset, line = locate(text, args.symbol, args.line, target)
        changes = create_inline(project, resource, offset).get_changes()
        return project, changes, target, args.symbol, "inline", not is_local(text, line, target)

    if args.command == "move-symbol":
        offset, _ = locate(text, args.symbol, args.line, target)
        destination_path = python_file(root, args.to, "--to")
        if args.symbol in module_level_names(
            destination_path.read_text(encoding="utf-8"), destination_path
        ):
            die(f"{destination_path.name} already defines {args.symbol!r} at module level")
        destination = libutils.path_to_resource(project, str(destination_path))
        changes = create_move(project, resource, offset).get_changes(destination)
        return project, changes, target, args.symbol, "move-symbol", True

    if args.command == "extract-method":
        if not args.name.isidentifier():
            die(f"--name {args.name!r} is not a Python identifier")
        first, _, last = args.lines.partition("-")
        if not first.strip().isdigit() or (last and not last.strip().isdigit()):
            die(f"--lines {args.lines!r} is not a FIRST-LAST line range, e.g. 27-31")
        start, end = line_span_offsets(text, int(first), int(last or first))
        changes = ExtractMethod(project, resource, start, end).get_changes(
            args.name, similar=args.similar
        )
        return project, changes, target, args.name, "extract-method", False

    if args.command == "extract-variable":
        if not args.name.isidentifier():
            die(f"--name {args.name!r} is not a Python identifier")
        lines = text.splitlines(keepends=True)
        if not 1 <= args.line <= len(lines):
            die(f"--line {args.line} is outside the file, which has {len(lines)} lines")
        column = lines[args.line - 1].find(args.expr)
        if column < 0:
            die(f"{args.expr!r} does not appear on line {args.line}")
        start = sum(len(item) for item in lines[: args.line - 1]) + column
        changes = ExtractVariable(project, resource, start, start + len(args.expr)).get_changes(
            args.name, similar=args.similar
        )
        return project, changes, target, args.name, "extract-variable", False

    die(f"unknown command {args.command!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=".", help="project root (default: cwd)")
    parser.add_argument("--apply", action="store_true", help="write the changes to disk")
    parser.add_argument(
        "--force", action="store_true", help="apply even when the coverage check says STOP"
    )
    parser.add_argument(
        "--import-style",
        default="from-global",
        choices=["from-global", "from-module", "normal-import"],
        help="how a move writes new imports; the default leaves call sites untouched",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    rename = sub.add_parser("rename", help="rename a symbol project-wide")
    rename.add_argument("--file", required=True)
    rename.add_argument("--symbol", required=True)
    rename.add_argument("--line", type=int, help="disambiguate when the name is defined twice")
    rename.add_argument("--to", required=True)
    rename.add_argument(
        "--docs",
        action="store_true",
        help="also rewrite the name inside docstrings and comments (mangles prose)",
    )

    inline = sub.add_parser("inline", help="inline a variable, function or method")
    inline.add_argument("--file", required=True)
    inline.add_argument("--symbol", required=True)
    inline.add_argument("--line", type=int)

    move_symbol = sub.add_parser("move-symbol", help="move a function or class to another module")
    move_symbol.add_argument("--file", required=True)
    move_symbol.add_argument("--symbol", required=True)
    move_symbol.add_argument("--line", type=int)
    move_symbol.add_argument("--to", required=True, help="destination .py file")

    move_module = sub.add_parser("move-module", help="move a module or package into a folder")
    move_module.add_argument("--module", required=True)
    move_module.add_argument("--to", required=True, help="destination folder")

    extract_method = sub.add_parser("extract-method", help="extract lines into a new method")
    extract_method.add_argument("--file", required=True)
    extract_method.add_argument("--lines", required=True, metavar="FIRST-LAST")
    extract_method.add_argument("--name", required=True)
    extract_method.add_argument("--similar", action="store_true", help="replace similar regions too")

    extract_variable = sub.add_parser("extract-variable", help="extract an expression into a name")
    extract_variable.add_argument("--file", required=True)
    extract_variable.add_argument("--line", type=int, required=True)
    extract_variable.add_argument("--expr", required=True, help="the expression, verbatim")
    extract_variable.add_argument("--name", required=True)
    extract_variable.add_argument("--similar", action="store_true")

    args = parser.parse_args()
    load_rope()

    from rope.base.exceptions import RopeError

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            project, changes, def_file, name, operation, propagates = build(args)
        except RopeError as refusal:
            die(f"rope refused this refactoring: {refusal}")
        unknown = {str(item.message) for item in caught if "Unknown node type" in str(item.message)}

    root = Path(args.project).resolve()
    status = report(changes, root, name, def_file, operation, propagates)

    for message in sorted(unknown):
        print(f"\nwarning: {message} — read the diff for that construct.", file=sys.stderr)

    if status != 0 and not args.force:
        project.close()
        return status

    if args.apply:
        unwritable = [
            path
            for path in sorted(
                Path(root, resource.path) for resource in changes.get_changed_resources()
            )
            if path.exists() and not os.access(path, os.W_OK)
        ]
        if unwritable:
            sys.stdout.flush()
            print("error: these files in the change set are not writable:", file=sys.stderr)
            for path in unwritable:
                print(f"  {path.relative_to(root)}", file=sys.stderr)
            die("nothing was applied — rope writes file by file and would stop half-way")
        try:
            project.do(changes)
        except OSError as failure:
            project.history.undo()
            die(f"apply failed and was rolled back: {failure}")
        print("\napplied.")
    else:
        print("\nnot applied — rerun with --apply.")
    project.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
