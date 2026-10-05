"""The README's facts: the paths it draws, the commands it prints, the tools it lists. Each table
row is mapped to what proves it, so a new row must say where it lives.
"""

import json
import re
import tomllib
from pathlib import Path

from tests.meta.readme import AGENTS, diagram_containing, normalised, text

_ROOT = Path(__file__).resolve().parents[2]

# Each stack row: what its Choice cell says, and its proof in a structured entry (a dependency,
# a file, the Python pin), never in prose.
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

# Each quality tool: its configuration, and its invocation in a gate (Makefile, CI, npm script,
# pre-commit); a version pin proves only an install.
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
    package = json.loads((_ROOT / "package.json").read_text())
    return "\n".join(
        [
            (_ROOT / "Makefile").read_text(),
            (_ROOT / ".github" / "workflows" / "ci.yml").read_text(),
            (_ROOT / "scripts" / ".pre-commit-config.yaml").read_text(),
            "\n".join(package.get("scripts", {}).values()),
        ]
    )


# Drawn in the tree, but built, not committed.
_GENERATED = {"static", "client"}

# What a drawn directory says it holds, as a glob it must match: an empty directory still exists.
_ROWS_HOLD = {
    "apps": "*/contract/integration.py",
    "docs": "*.md",
    "features": "*.feature",
    "supabase/migrations": "*.sql",
    "tests": "plugin.py",
}


def _table_rows(header: str) -> dict[str, str]:
    block = text()[text().index(header) :]
    rows = block[: block.index("\n\n")].splitlines()[2:]
    cells = [[cell.strip() for cell in row.strip().strip("|").split("|")] for row in rows]
    return {row[0]: row[1] for row in cells}


def _tree_paths() -> list[str]:
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
    """Each row exists, and holds the content its comment names."""
    drawn = _tree_paths()
    missing = {
        path
        for path in drawn
        if path.split("/")[0] not in _GENERATED
        and not (
            list((_ROOT / path).parent.glob(Path(path).name))
            if "*" in path
            else (_ROOT / path).exists()
        )
    }
    undrawn = {path for path in _ROWS_HOLD if path not in drawn}
    hollow = {
        f"{path}/ holds no {pattern}"
        for path, pattern in _ROWS_HOLD.items()
        if not list((_ROOT / path).glob(pattern))
    }

    assert (missing, undrawn, hollow) == (set(), set(), set())


def _make_targets() -> dict[str, tuple[list[str], list[str]]]:
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
    """Targets `make <target>` runs: prerequisites and sub-makes."""
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
    """Each printed target exists and reaches the phases its comment composes
    (`# js-build + fix + lint + test`), when they all name targets."""
    targets = _make_targets()
    documented = re.findall(r"^make ([a-z][\w-]*)[^#\n]*(?:#\s*([^\n]*))?$", text(), re.MULTILINE)

    missing = {name for name, _ in documented if name not in targets}
    unreached = set()
    for name, comment in documented:
        phases = [phase.strip() for phase in comment.split(",")[0].split("(")[0].split("+")]
        # Tools ("ruff + biome + …") are prose, not a composition.
        if name in targets and phases and all(phase in targets for phase in phases):
            unreached |= {
                f"{name} says it runs {phase}"
                for phase in phases
                if phase not in _reachable(name, targets)
            }

    assert (missing, unreached) == (set(), set())


def test_the_stack_table_names_what_is_installed():
    rows = _table_rows("| Layer")

    unsaid = {
        label for label, (choice, _, _) in _STACK.items() if choice not in rows.get(label, "")
    }
    unproved = {label for label, (_, kind, needle) in _STACK.items() if not _proved(kind, needle)}

    assert (set(rows), unsaid, unproved) == (set(_STACK), set(), set())


def test_every_quality_tool_in_the_table_is_still_configured():
    rows = _table_rows("| Tool")
    gates = _gates()

    unconfigured = {
        label for label, ((kind, needle), _) in _TOOLS.items() if not _proved(kind, needle)
    }
    ungated = {label for label, (_, invocation) in _TOOLS.items() if invocation not in gates}

    assert (set(rows), unconfigured, ungated) == (set(_TOOLS), set(), set())


def test_the_test_environment_file_is_committed_and_local():
    """`.env.test` is committed and points at `127.0.0.1`: not the Docker host (the wrong stack),
    not `localhost` (DNS may answer `::1`)."""
    env_test = _ROOT / ".env.test"
    ignored = ".env.test" in (_ROOT / ".gitignore").read_text()
    body = env_test.read_text()

    assert (
        env_test.exists(),
        ignored,
        "127.0.0.1" in body,
        "localhost" in body,
        "host.docker.internal" in body,
    ) == (True, False, True, False, False)


def test_every_rule_pointer_names_something_agents_md_says():
    """An `(AGENTS: …)` pointer quotes AGENTS.md text, or it points at nothing; the README holds no
    rules to point at."""
    agents = normalised(AGENTS.read_text()).lower()

    dangling = {
        f"{path.relative_to(_ROOT)}: {document}: {claim}"
        for path in sorted(_ROOT.glob("apps/**/*.py"))
        if "/tests/" not in path.as_posix()
        for document, claim in re.findall(
            r"\((README|AGENTS):\s*([^)]+)\)", " ".join(path.read_text().split())
        )
        if document == "README" or claim.strip().rstrip(".").lower() not in agents
    }

    assert dangling == set()


def test_claude_md_imports_agents_md_rather_than_asking_for_it():
    """An `@AGENTS.md` import loads the principles in every session; an instruction to read it
    can be skipped."""
    imports = [
        line for line in (_ROOT / "CLAUDE.md").read_text().splitlines() if line.startswith("@")
    ]

    assert imports == ["@AGENTS.md"]


def _github_anchor(title: str) -> str:
    return re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")


def _sections() -> list[tuple[int, str]]:
    """``(level, title)`` of AGENTS.md's ``##`` and ``###`` headings, fences aside."""
    found, fenced = [], False
    for line in AGENTS.read_text().splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and (match := re.match(r"(#{2,3}) (.+)$", line)):
            found.append((len(match[1]), match[2]))
    return found


def test_the_readme_lists_every_section_of_agents_md_linked_to_its_text():
    """The README links every heading, in order, saying nothing else of them."""
    listed = [line for line in text().splitlines() if "](AGENTS.md#" in line]

    assert listed == [
        f"{'  ' * (level - 2)}- [{title}](AGENTS.md#{_github_anchor(title)})"
        for level, title in _sections()
    ]


def test_a_subject_of_agents_md_holds_nothing_but_its_principles():
    """A ``##`` subject only groups its ``###`` principles."""
    subjects = re.findall(
        r"^## (.+?)\n(.*?)(?=^##)", AGENTS.read_text() + "\n##", flags=re.MULTILINE | re.DOTALL
    )

    loose = [title for title, body in subjects if body.strip()]

    assert loose == []
