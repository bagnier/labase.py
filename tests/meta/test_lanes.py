"""The dual-lane promise: one scenario file, two drivers, and no quiet way out of either.

"The same plain-language scenarios run twice" is the base's central testing claim, and it is held
up by a single thread — a scenario file bound by ``scenarios(...)`` runs under whichever driver
the session was started with, so both lanes collect the same nodes. Three things can cut that
thread, none of them loudly:

- a ``.feature`` file nobody binds. It lints, it reads well, it runs in *neither* lane, and the
  behaviour it describes is covered by nothing at all.
- a ``@web`` tag. It is the one sanctioned way to run a scenario once instead of twice, which
  makes it the one thing worth counting: the tag is a decision, so it is written down here and
  growing the list means changing this file.
- a context with steps and one driver mixin, whose scenarios can only ever have run on one side.

What no test can hold is the deeper half of the claim — that both mixins mean the *same thing* by
a step. That stays a review question, and the README should not be read as promising more.
"""

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_FEATURES = _ROOT / "features"

# Browser-only scenarios, named one by one. A scenario tagged `@web` runs once, not twice — the
# claim's only sanctioned exception, and it costs a line here.
_BROWSER_ONLY = {
    "profile.feature: The profile is reached from the account area, not the main navigation",
}


def _scenario_bindings() -> dict[str, list[str]]:
    """Every ``.feature`` file bound by a ``scenarios(...)`` call, mapped to the modules binding
    it — the only thing that turns Gherkin into collected tests."""
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
                    bound.setdefault(Path(str(arg.value)).name, []).append(
                        str(module.relative_to(_ROOT))
                    )
    return bound


def _tagged_scenarios() -> set[str]:
    """Every ``@web`` scenario, as ``file: title`` — the tag sits on the line above its
    ``Scenario:``, which is what makes it readable without a Gherkin parser."""
    tagged = set()
    for feature in sorted(_FEATURES.glob("*.feature")):
        lines = feature.read_text().splitlines()
        for index, line in enumerate(lines):
            if line.strip() != "@web":
                continue
            title = next(
                (
                    rest.strip()
                    for following in lines[index + 1 :]
                    if (rest := re.sub(r"^\s*Scenario( Outline)?:", "", following)) != following
                ),
                "«no scenario under the tag»",
            )
            tagged.add(f"{feature.name}: {title}")
    return tagged


def test_every_scenario_file_is_bound_exactly_once():
    """Bound twice is two runs of the same scenario; bound never is a feature file that describes
    behaviour nothing exercises — the failure this claim is most exposed to, since a `.feature`
    with no test module still passes gherkin-lint and still reads as covered."""
    bindings = _scenario_bindings()

    unbound = {feature.name for feature in _FEATURES.glob("*.feature")} - set(bindings)
    duplicated = {name: modules for name, modules in bindings.items() if len(modules) > 1}
    dangling = {name for name in bindings if not (_FEATURES / name).exists()}

    assert (unbound, duplicated, dangling) == (set(), {}, set())


def test_only_the_named_scenarios_run_on_one_driver():
    """`@web` is the sanctioned way to run once instead of twice. Sanctioned, and countable: a
    scenario that quietly becomes browser-only because it grew a DOM-shaped assertion is the way
    "the same scenarios run twice" stops being true one scenario at a time."""
    assert _tagged_scenarios() == _BROWSER_ONLY


def test_every_context_with_steps_drives_both_lanes():
    """Steps call the driver; the mixins are what a driver is. One mixin means the context's
    scenarios were only ever written against one surface, whatever the tags say."""
    lonely = {
        f"{steps.parts[-4]} has no {driver} mixin"
        for steps in sorted(_ROOT.glob("apps/*/tests/e2e/steps.py"))
        for driver in ("api", "browser")
        if not (steps.parent / f"driver_mixin_{driver}.py").exists()
    }

    assert lonely == set()
