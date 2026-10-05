"""Every scenario runs on both drivers (AGENTS: tests are sincere): each ``.feature`` file is
bound, ``@web`` exceptions are listed, each context has both mixins. That both mixins mean the same
by a step stays a review question.
"""

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_FEATURES = _ROOT / "features"

# The `@web` scenarios, run on the browser only.
_BROWSER_ONLY = {
    "profile.feature: The profile is reached from the account area, not the main navigation",
    "files.feature: The upload control has an accessible name",
    "files.feature: The share link field has an accessible name",
    (
        "files.feature: A file row's rename, share and delete controls stay visible when"
        " focused by keyboard"
    ),
    "todo.feature: A todo row's edit and delete buttons stay visible when reached by keyboard",
    "todo.feature: Renaming a todo item from the keyboard reaches a labelled field",
}


def _scenario_bindings() -> dict[str, list[str]]:
    """Each ``.feature`` bound by ``scenarios(...)``, with its binding modules."""
    bound: dict[str, list[str]] = {}
    for module in sorted(_ROOT.glob("apps/*/tests/e2e/test_*.py")):
        for node in ast.walk(ast.parse(module.read_text())):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"scenario", "scenarios"}
            ):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and str(arg.value).endswith(".feature"):
                    modules = bound.setdefault(Path(str(arg.value)).name, [])
                    # A `scenario(...)` beside `scenarios(...)` is one binding.
                    if str(module.relative_to(_ROOT)) not in modules:
                        modules.append(str(module.relative_to(_ROOT)))
    return bound


def _tagged_scenarios() -> set[str]:
    """``@web`` scenarios as ``file: title``, parsed: tags stack, share lines, or tag a whole
    ``Feature:``."""
    tagged = set()
    for feature in sorted(_FEATURES.glob("*.feature")):
        pending: set[str] = set()
        feature_tags: set[str] = set()
        for raw in feature.read_text().splitlines():
            line = raw.strip()
            if line.startswith("@"):
                pending |= set(line.split())
            elif line.startswith("Feature:"):
                feature_tags, pending = pending, set()
            elif (title := re.sub(r"^Scenario( Outline)?:", "", line)) != line:
                if "@web" in pending | feature_tags:
                    tagged.add(f"{feature.name}: {title.strip()}")
                pending = set()
            elif line and not line.startswith("#"):
                pending = set()
    return tagged


def test_every_scenario_file_is_bound_exactly_once():
    """Unbound, a `.feature` lints and runs nowhere; bound twice, it runs twice."""
    bindings = _scenario_bindings()

    unbound = {feature.name for feature in _FEATURES.glob("*.feature")} - set(bindings)
    duplicated = {name: modules for name, modules in bindings.items() if len(modules) > 1}
    dangling = {name for name in bindings if not (_FEATURES / name).exists()}

    assert (unbound, duplicated, dangling) == (set(), {}, set())


def test_only_the_named_scenarios_run_on_one_driver():
    assert _tagged_scenarios() == _BROWSER_ONLY


def test_the_browser_lane_collects_every_scenario_module():
    """`make test-e2e` selects with `-k`: an unmatched module runs in the API lane only."""
    makefile = (_ROOT / "Makefile").read_text()
    selection = re.search(r'test-e2e:.*?\n\t.*? -k "([^"]+)"', makefile, flags=re.DOTALL)
    assert selection is not None, "the browser lane no longer selects with -k — update this walk"

    terms = [term.strip() for term in selection.group(1).split(" or ")]
    deselected = {
        module
        for modules in _scenario_bindings().values()
        for module in modules
        if not any(term in Path(module).stem for term in terms)
    }

    assert deselected == set()


def test_every_context_with_steps_drives_both_lanes():
    lonely = {
        f"{steps.parts[-4]} has no {driver} mixin"
        for steps in sorted(_ROOT.glob("apps/*/tests/e2e/steps.py"))
        for driver in ("api", "browser")
        if not (steps.parent / f"driver_mixin_{driver}.py").exists()
    }

    assert lonely == set()
