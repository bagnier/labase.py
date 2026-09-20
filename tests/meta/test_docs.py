"""The README's factual half — the paths it draws, the commands it prints, the tools it lists.

None of this is architecture; all of it is what a newcomer types in the first hour. It is also the
part that rots fastest and most invisibly, because it is the part nobody re-reads: a renamed
directory, a target dropped from the Makefile, a linter removed from the dev group all leave the
README saying something that was true once.

The two tables are held by an explicit map from the README's own row labels to the string that
proves the row. Asserting the labels *are* the map's keys is what makes a new row a decision:
adding a tool to the table without saying where it lives fails here.
"""

import json
import re
import tomllib
from pathlib import Path

from tests.meta.readme import diagram_containing, normalised, text

_ROOT = Path(__file__).resolve().parents[2]

# Each stack row: what its Choice cell must still say, and what proves it — a real dependency
# entry (pyproject / package.json), a file the tool owns, or the pinned Python version. Proving
# from structured entries is what stops a comment or the project description answering for a
# dependency that was dropped.
_STACK = {
    "**Web framework**": ("FastAPI", "dependency", "fastapi"),
    "**HTML rendering**": ("Jinja2", "dependency", "jinja2"),
    "**Styling**": ("daisyUI", "dependency", "daisyui"),
    "**ORM**": ("SQLAlchemy", "dependency", "sqlalchemy"),
    "**Auth + Storage**": ("supabase-py", "dependency", "supabase"),
    "**Database**": ("Supabase", "file", "supabase/config.toml"),
    "**Migrations**": ("Supabase CLI", "file", "supabase/migrations"),
    "**ASGI server**": ("Hypercorn", "dependency", "hypercorn"),
    "**Dependency management**": ("uv", "file", "uv.lock"),
    "**Python**": ("3.14", "requires-python", "3.14"),
}

# Each quality tool: its configuration, and its invocation in a gate someone runs (the Makefile,
# the CI workflow, an npm script, the pre-commit hooks). A version pin alone proves an install,
# not a gate — which is how a tool could leave the build while its row stayed green.
_TOOLS = {
    "**ruff**": (("pyproject", "[tool.ruff"), "ruff check"),
    "**Biome**": (("file", "biome.json"), "biome"),
    "**djlint**": (("pyproject", "[tool.djlint"), "djlint apps"),
    "**sqlfluff**": (("file", "scripts/.sqlfluff"), "sqlfluff lint"),
    "**gplint**": (("file", "scripts/.gplintrc"), "gplint"),
    "**yamllint**": (("file", "scripts/.yamllint"), "yamllint"),
    "**validate-pyproject**": (("dependency", "validate-pyproject"), "validate-pyproject"),
    "**zizmor**": (("file", ".github/zizmor.yml"), "zizmor"),
    "**droast**": (("workflow", "droast"), "droast"),
    "**ty**": (("dependency", "ty"), "ty check"),
    "**pyright**": (("pyproject", "[tool.pyright"), "pyright"),
    "**import-linter**": (("pyproject", "[tool.importlinter"), "lint-imports"),
    "**pip-audit**": (("dependency", "pip-audit"), "pip-audit"),
    "**pre-commit**": (("file", "scripts/.pre-commit-config.yaml"), "pre-commit install"),
    "**pytest + pytest-asyncio**": (("pyproject", "[tool.pytest.ini_options"), "pytest"),
    "**pytest-bdd + Playwright**": (("dependency", "pytest-bdd"), "--driver=browser"),
    "**coverage**": (("dependency", "coverage"), "coverage run"),
}


def _dependency_names() -> set[str]:
    """The names actually depended on — pyproject's dependencies and groups, npm's two maps."""
    config = tomllib.loads((_ROOT / "pyproject.toml").read_text())
    specs = list(config["project"]["dependencies"])
    for group in config.get("dependency-groups", {}).values():
        specs += [spec for spec in group if isinstance(spec, str)]
    package = json.loads((_ROOT / "package.json").read_text())
    return (
        {re.split(r"[\s\[<>=~!]", spec)[0].lower() for spec in specs}
        | {name.lower() for name in package.get("dependencies", {})}
        | {name.lower() for name in package.get("devDependencies", {})}
    )


def _proved(kind: str, needle: str) -> bool:
    if kind == "dependency":
        return needle in _dependency_names()
    if kind == "file":
        return (_ROOT / needle).exists()
    if kind == "pyproject":
        return needle in (_ROOT / "pyproject.toml").read_text()
    if kind == "workflow":
        return needle in (_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    if kind == "requires-python":
        config = tomllib.loads((_ROOT / "pyproject.toml").read_text())
        return needle in config["project"]["requires-python"]
    raise ValueError(kind)


def _gates() -> str:
    """Everywhere an invocation counts as being part of the gate."""
    package = json.loads((_ROOT / "package.json").read_text())
    return "\n".join(
        [
            (_ROOT / "Makefile").read_text(),
            (_ROOT / ".github" / "workflows" / "ci.yml").read_text(),
            (_ROOT / "scripts" / ".pre-commit-config.yaml").read_text(),
            "\n".join(package.get("scripts", {}).values()),
        ]
    )


# Drawn in the structure tree and produced by the build rather than committed: `static/` is
# gitignored (`make install` rebuilds it) and `client/` is regenerated by `make client-gen`.
_GENERATED = {"static", "client"}


def _table_rows(header: str) -> dict[str, str]:
    """The README table starting at ``header``, as ``{first cell: second cell}``."""
    block = text()[text().index(header) :]
    rows = block[: block.index("\n\n")].splitlines()[2:]
    cells = [[cell.strip() for cell in row.strip().strip("|").split("|")] for row in rows]
    return {row[0]: row[1] for row in cells}


def _tree_paths() -> list[str]:
    """Every path the structure tree draws, resolved against the repo root."""
    stack: list[str] = []
    paths = []
    for row in diagram_containing("labase.py/").splitlines():
        drawn_line = row.split("#")[0].rstrip()
        if not drawn_line.strip():
            continue
        drawn = re.match(r"^([│\s├└─]*?)([\w./*-]+/?)$", drawn_line)
        assert drawn is not None, f"the structure tree drew a line nothing can read: {row!r}"
        prefix, name = drawn.groups()
        stack = [*stack[: len(prefix) // 4], name.rstrip("/")]
        if stack[0] == "labase.py" and len(stack) > 1:
            paths.append("/".join(stack[1:]))
    return paths


def test_every_path_the_structure_tree_draws_exists():
    """A tree is the first thing read and the last thing updated."""
    missing = {
        path
        for path in _tree_paths()
        if path.split("/")[0] not in _GENERATED
        and not (
            list((_ROOT / path).parent.glob(Path(path).name))
            if "*" in path
            else (_ROOT / path).exists()
        )
    }

    assert missing == set()


def _make_targets() -> dict[str, tuple[list[str], list[str]]]:
    """The Makefile as a graph: ``{target: (prerequisites, recipe lines)}``."""
    targets: dict[str, tuple[list[str], list[str]]] = {}
    current = None
    for line in (_ROOT / "Makefile").read_text().splitlines():
        if header := re.match(r"^([a-z][\w-]*):(.*)$", line):
            current = header.group(1)
            prerequisites = [
                word
                for word in header.group(2).split()
                if re.fullmatch(r"[a-z][\w-]*", word) is not None
            ]
            targets[current] = (prerequisites, [])
        elif line.startswith("\t") and current is not None:
            targets[current][1].append(line.strip())
    return targets


def _reachable(target: str, targets: dict[str, tuple[list[str], list[str]]]) -> set[str]:
    """Every target a `make <target>` will run — prerequisites, plus sub-makes in the recipe."""
    reached: set[str] = set()
    frontier = [target]
    while frontier:
        name = frontier.pop()
        if name in reached or name not in targets:
            continue
        reached.add(name)
        prerequisites, recipe = targets[name]
        frontier += prerequisites
        frontier += [
            word for line in recipe if "$(MAKE)" in line for word in line.split() if word in targets
        ]
    return reached


def test_every_documented_command_exists():
    """The README prints its `make` targets, most with their composition (`# js-build + fix +
    lint + test`). A target renamed answers "No rule to make target"; a composition the target
    no longer reaches — a phase dropped, a recipe gutted to an echo — fails here instead of in a
    newcomer's terminal. Only comments whose phases all name make targets are compositions."""
    targets = _make_targets()
    documented = re.findall(r"^make ([a-z][\w-]*)[^#\n]*(?:#\s*([^\n]*))?$", text(), re.MULTILINE)

    missing = {name for name, _ in documented if name not in targets}
    unreached = set()
    for name, comment in documented:
        phases = [phase.strip() for phase in comment.split(",")[0].split("(")[0].split("+")]
        # A composition names make targets ("js-build + fix + lint + test"); a comment listing
        # the tools a recipe runs ("ruff + biome + …") is prose, and stays one.
        if name in targets and phases and all(phase in targets for phase in phases):
            unreached |= {
                f"{name} says it runs {phase}"
                for phase in phases
                if phase not in _reachable(name, targets)
            }

    assert (missing, unreached) == (set(), set())


def test_the_stack_table_names_what_is_installed():
    """Ten rows, each held at both ends: the Choice cell still says what the row promises, and a
    structured build entry — not a stray word in a comment — still backs it."""
    rows = _table_rows("| Layer")

    unsaid = {
        label for label, (choice, _, _) in _STACK.items() if choice not in rows.get(label, "")
    }
    unproved = {label for label, (_, kind, needle) in _STACK.items() if not _proved(kind, needle)}

    assert (set(rows), unsaid, unproved) == (set(_STACK), set(), set())


def test_every_quality_tool_in_the_table_is_still_configured():
    """Eighteen tools advertised as the gate — so each row is held by its configuration *and* by
    an invocation in something someone runs (Makefile, CI, an npm script, the pre-commit hooks).
    A version pin alone proves an install, which is how a tool once left the gate unnoticed."""
    rows = _table_rows("| Tool")
    gates = _gates()

    unconfigured = {
        label for label, ((kind, needle), _) in _TOOLS.items() if not _proved(kind, needle)
    }
    ungated = {label for label, (_, invocation) in _TOOLS.items() if invocation not in gates}

    assert (set(rows), unconfigured, ungated) == (set(_TOOLS), set(), set())


def test_the_test_environment_file_is_committed_and_local():
    """`.env.test` is the one env file the README says is in the repo, because `make test` reads it
    and points it at localhost — a `.env.test` that drifted to the docker host silently runs the
    suite against the wrong stack."""
    env_test = _ROOT / ".env.test"
    ignored = ".env.test" in (_ROOT / ".gitignore").read_text()

    assert (env_test.exists(), ignored, "host.docker.internal" in env_test.read_text()) == (
        True,
        False,
        False,
    )


def test_every_readme_pointer_names_something_the_readme_says():
    """`(README: the log sink)` in a module docstring is a promise that the README carries the rule
    this file only applies. The pointer is prose, so a reworded heading leaves it pointing at
    nothing and the module quietly becomes the only statement again — which is the duplication the
    pointers were introduced to end."""
    readme = normalised(text()).lower()

    dangling = {
        f"{path.relative_to(_ROOT)}: {claim}"
        for path in sorted(_ROOT.glob("apps/**/*.py"))
        if "/tests/" not in path.as_posix()
        for claim in re.findall(r"\(README:\s*([^)]+)\)", " ".join(path.read_text().split()))
        if claim.strip().rstrip(".").lower() not in readme
    }

    assert dangling == set()
