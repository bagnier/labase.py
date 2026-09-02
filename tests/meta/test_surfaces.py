"""What every app must declare, checked against the mount surface rather than against its prose.

The README's integration section is one long promise about *uniformity*: every context mounts the
same way, contributes through the same registries, and is therefore deletable without a trace.
Uniformity is the kind of claim that decays one app at a time — the app that skips the console
tile, the shared module that learns one context's name, the contract nobody adds to
``pyproject.toml`` — and none of those breaks anything the day it lands. They only make the
sentence in the README a little less true.

Everything here reads a *declaration*: the manifest an app passes to ``Host.register_app``, the
module list the composition root sorts, the contracts import-linter enforces. Nothing here reads
behaviour — that is what the rest of the suite is for.
"""

import ast
import re
import tomllib
from pathlib import Path

import apps.main  # noqa: F401  — mounting every app fills the catalog and the slug registry
from apps.issues.contract.events import IssueOpened, IssueRegressed
from apps.shared.events import BusinessEvent
from apps.shared.events.catalog import catalog
from apps.shared.logs.capture import ExceptionCaptured

_ROOT = Path(__file__).resolve().parents[2]
_APPS = _ROOT / "apps"

# Postgres' own schema, not the `public` context. The only word in `apps/shared` that collides
# with a bounded context's name, and it predates the context by every migration in the repo.
_POSTGRES_SCHEMA = ("apps/shared/settings/env.py", "public")


def _contexts() -> set[str]:
    """Every bounded context — the packages under ``apps/`` except the shared foundation."""
    return {
        path.name
        for path in _APPS.iterdir()
        if (path / "__init__.py").exists() and path.name != "shared"
    }


def _module_names(path: Path) -> set[str]:
    """The names a module binds at its top level — functions, classes and plain assignments."""
    tree = ast.parse(path.read_text())
    names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    return names | {
        target.id
        for node in tree.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }


def _contracts() -> list[dict]:
    config = tomllib.loads((_ROOT / "pyproject.toml").read_text())
    return config["tool"]["importlinter"]["contracts"]


def _contract_named(name: str) -> dict:
    return next(contract for contract in _contracts() if contract["name"] == name)


def test_every_context_declares_one_mount_entry_point():
    """`contract/integration.py`, a `mount` and a `PHASE`: the composition root calls nothing else,
    so a context missing one of the three is a context that cannot be mounted at all."""
    incomplete = {
        name
        for name in _contexts()
        if not (integration := _APPS / name / "contract" / "integration.py").exists()
        or not {"mount", "PHASE"} <= _module_names(integration)
    }

    assert incomplete == set()


def test_the_composition_root_mounts_every_context():
    """An app nobody mounts is an app that ships dead: no routes, no tile, no seeds — and no
    failure either, which is why this is worth a test rather than a code review."""
    root = ast.parse((_APPS / "main.py").read_text())
    mounted_tuple = next(
        node.value
        for node in root.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_apps" for target in node.targets)
    )

    # `_apps = sorted((…), key=…)`: the mounted contexts are the sorted call's first argument,
    # not its key function.
    listed = mounted_tuple.args[0] if isinstance(mounted_tuple, ast.Call) else mounted_tuple

    mounted = {node.id for node in ast.walk(listed) if isinstance(node, ast.Name)}

    assert mounted == _contexts() | {"shared"}


def test_the_shared_foundation_is_forbidden_from_every_context():
    """`shared imports no bounded context` names its contexts one by one, so a new app is outside
    the contract until someone extends the list — the one place the boundary is opt-in."""
    contract = _contract_named("shared imports no bounded context")

    forbidden = {module.removeprefix("apps.") for module in contract["forbidden_modules"]}

    assert forbidden == _contexts()


def test_every_context_keeps_its_internals_private():
    """One `protected` contract per context. Same failure mode as above, one level down: a context
    that never gets its contract can be imported through `domain/` by anyone, and the README's
    "the only inter-app surfaces are each app's public contract" quietly stops holding."""
    protected = {
        contract["name"].removesuffix(" internals are private")
        for contract in _contracts()
        if contract["type"] == "protected"
    }

    assert protected == _contexts()


def test_the_one_way_edge_out_of_auth_is_contracted():
    """The README names this edge specifically as the example of import-downward-event-upward."""
    contract = _contract_named("auth is a foundation: it never imports the organizations context")

    assert (contract["source_modules"], contract["forbidden_modules"]) == (
        ["apps.auth"],
        ["apps.organizations"],
    )


def _shared_strings_naming_a_context() -> set[str]:
    """Every non-docstring string literal under `apps/shared` that spells a context's name."""
    contexts = _contexts()
    found = set()
    for path in sorted((_APPS / "shared").rglob("*.py")):
        if "/tests/" in path.as_posix():
            continue
        tree = ast.parse(path.read_text())
        # A docstring is the first statement of its module, class or function — an expression
        # holding the constant. Matched by identity, so a prose mention of a context's name costs
        # nothing while the same string in code counts.
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
            and ast.get_docstring(node) is not None
            and isinstance(node.body[0], ast.Expr)
        }
        relative = str(path.relative_to(_ROOT))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in contexts
                and id(node) not in docstrings
                and (relative, node.value) != _POSTGRES_SCHEMA
            ):
                found.add(f"{relative}:{node.lineno} says {node.value!r}")
    return found


def test_no_shared_module_names_a_bounded_context():
    """The whole "delete an app and nothing is left behind" promise rests here.

    import-linter already forbids shared *importing* a context; a string is how the rule gets
    broken without one — a settings key, a nav slug, a template path, an `if app == "metrics"`.
    Each one survives the app's deletion as a dangling reference to something that no longer
    exists, which is exactly the trace the README says cannot remain.
    """
    assert _shared_strings_naming_a_context() == set()


def test_every_context_declares_its_console_tile():
    """The tile is what makes an app visible to an admin — and what lets a *disabled* one be
    switched back on, since it registers before the enabled gate."""
    silent = {
        name
        for name in _contexts()
        if "ConsoleOverviewQuery" not in (_APPS / name / "contract" / "integration.py").read_text()
    }

    assert silent == set()


def _writes_under(package: str) -> set[str]:
    """Every site under ``apps/<package>`` that could change stored state.

    Three shapes, and no more: a fact emitted, a row handed to a session, or SQLAlchemy's own DML
    imported. Naming the receiver is what keeps ``values.add(selected)`` — a set, in a facet
    builder — from reading as a database write.
    """
    session_writes = {"add", "add_all", "merge"}
    dml = {"insert", "update", "delete"}
    found = set()
    for path in sorted((_APPS / package).rglob("*.py")):
        if "/tests/" in path.as_posix():
            continue
        site = f"{path.relative_to(_ROOT)}"
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("sqlalchemy"):
                found |= {
                    f"{site}:{node.lineno} imports {a.name}" for a in node.names if a.name in dml
                }
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == "emit":
                found.add(f"{site}:{node.lineno} emits a fact")
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr in session_writes
                and isinstance(node.func.value, ast.Name)
                and "session" in node.func.value.id
            ):
                found.add(f"{site}:{node.lineno} calls {node.func.value.id}.{node.func.attr}()")
    return found


def test_the_timeline_writes_nothing():
    """A read view that starts writing is a fourth source to correlate against the other three."""
    assert _writes_under("timeline") == set()


def _keywords_passed_to(class_name: str) -> set[str]:
    """Every keyword argument any construction of ``class_name`` passes, across ``apps/``."""
    return {
        keyword.arg or ""
        for path in _APPS.rglob("*.py")
        if "/tests/" not in path.as_posix()
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == class_name
        for keyword in node.keywords
    }


def test_an_issue_fact_never_names_the_user_who_tripped_it():
    """The journal is readable by whoever it names. An internal issue named after the user who
    happened to hit it would surface, in that person's own activity feed, a bug that is not
    theirs — and would do it through RLS, correctly, which is what makes it hard to notice."""
    named = {
        f"{cls.__name__}(user_id=…)"
        for cls in (IssueOpened, IssueRegressed)
        if "user_id" in _keywords_passed_to(cls.__name__)
    }

    assert named == set()


def test_the_capture_seam_is_not_a_business_fact():
    """`ExceptionCaptured` travels from the logs context to the issues context directly, so a
    tracker that fails cannot worsen the exception it tracks. Making it a fact would put it on the
    journal, on a transaction, in the timeline's `business` source — three wrong answers."""
    assert (
        issubclass(ExceptionCaptured, BusinessEvent),
        ExceptionCaptured in catalog.kinds().values(),
    ) == (False, False)


def test_the_reference_app_fills_every_surface():
    """`todo/` is what a new app is copied from, so a surface it stops demonstrating is a surface
    the next app will not have. The README lists them by name; this is that list."""
    manifest = (_APPS / "todo" / "contract" / "integration.py").read_text()
    surfaces = {
        "nav": "nav=",
        "dashboard overview": "provides_when_enabled=",
        "console overview": "ConsoleOverviewQuery",
        "settings": "settings=",
        "feature switch": "feature_switch()",
        "seeding": "consumes_when_enabled=",
        "routes": "routers=",
        "events": "emits=",
    }

    missing = {name for name, spelling in surfaces.items() if spelling not in manifest} | {
        f"{driver} driver"
        for driver in ("api", "browser")
        if not (_APPS / "todo" / "tests" / "e2e" / f"driver_mixin_{driver}.py").exists()
    }

    assert missing == set()


# The icon font shipped in `static/fonts/` is Phosphor's full regular set, but the CSS that names
# its glyphs is curated by hand — a surface may therefore declare an icon the stylesheet has no
# rule for, and the tile renders a blank square. Nothing fails, nothing logs; the tile is simply
# mute, which is precisely the kind of decay a declaration-level walk exists to catch.
_ICON_CSS = _ROOT / "static" / "css" / "input.css"


def _icons_with_a_rule() -> set[str]:
    return set(re.findall(r"\.ph\.ph-([a-z0-9-]+):before", _ICON_CSS.read_text()))


def _icons_declared() -> dict[str, str]:
    """Every ``icon="…"`` a surface passes, mapped to where it says it. Tests aside: a fixture may
    name an icon nothing renders."""
    found = {}
    for path in sorted(_APPS.rglob("*.py")):
        if "/tests/" in path.as_posix():
            continue
        for icon in re.findall(r'icon="([a-z0-9-]+)"', path.read_text()):
            found[icon] = str(path.relative_to(_ROOT))
    return found


def test_every_icon_a_surface_declares_has_a_glyph_to_render():
    """A tile whose icon has no CSS rule shows an empty box — and only a human looking at the
    page ever finds out."""
    declared = _icons_declared()

    with_rule = _icons_with_a_rule()

    mute = {f"{icon} ({site})" for icon, site in declared.items() if icon not in with_rule}

    assert mute == set()


def test_the_icon_walk_actually_finds_the_declarations():
    # Guards the guard: a regex that matched nothing would make the assertion above vacuous.
    assert len(_icons_declared()) > 10


# ``data-hash-tabs`` is an opt-in: the markup asks for the behaviour, and the page has to load the
# script that provides it. Forget the script and nothing breaks loudly — the tabs still switch,
# they just stop surviving a reload and stop being linkable, which is exactly the kind of silence
# a declaration-level walk is for.
_TEMPLATES = sorted(_APPS.glob("*/templates/**/*.html"))
_HASH_TABS_SCRIPT = "js/hash-tabs.js"


def _pages_opting_into_hash_tabs() -> dict[str, str]:
    return {
        str(path.relative_to(_ROOT)): path.read_text()
        for path in _TEMPLATES
        if "data-hash-tabs" in path.read_text()
    }


def test_every_page_with_hash_tabs_loads_the_script_that_makes_them_work():
    opted_in = _pages_opting_into_hash_tabs()

    silent = {site for site, body in opted_in.items() if _HASH_TABS_SCRIPT not in body}

    assert silent == set()


def test_the_hash_tabs_walk_actually_finds_the_pages():
    # Guards the guard: a glob that matched nothing would make the assertion above vacuous.
    assert len(_pages_opting_into_hash_tabs()) > 1
