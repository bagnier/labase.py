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
import inspect
import re
import tomllib
import typing
from pathlib import Path

import pytest
from sqlalchemy import Table

import apps.main
from apps.console.contract.overviews import ConsoleOverviewQuery
from apps.issues.contract.events import IssueOpened, IssueRegressed
from apps.organizations.contract.overviews import OverviewQuery
from apps.shared.events import BusinessEvent
from apps.shared.events.bus import EventBus
from apps.shared.events.catalog import catalog
from apps.shared.integration.contribs import Contribs
from apps.shared.integration.host import Host
from apps.shared.logs.capture import ExceptionCaptured
from apps.shared.persistence.base import Base
from apps.shared.settings import live
from apps.tasks.domain.strip import BANDS
from apps.todo.contract import integration as todo_integration
from tests.meta.test_ratchets import _demos

_ROOT = Path(__file__).resolve().parents[2]
_APPS = _ROOT / "apps"

# Strings through which `apps/shared` names a context *on purpose* — each one a real coupling the
# guard below would otherwise report, kept visible here rather than suppressed in the walk. A new
# entry is a decision: is this the multi-tenancy floor, or a trace an app's deletion would leave?
_NAMED_ON_PURPOSE = {
    # The journal writer pins the actor's handle and org name onto each fact, so a later deletion
    # or RLS cannot hide who and where — the one shared SQL allowed to read those two tables.
    "apps/shared/events/repository.py says 'organizations'",
    "apps/shared/events/repository.py says 'profiles'",
    # The 401 handler bounces a browser to the sign-in form; that URL is auth's.
    "apps/shared/http/exceptions.py says '/auth'",
    # The request logger skips the probes' own polling; the probe paths are health's.
    "apps/shared/logs/request.py says '/health'",
    # Multi-tenancy's floor: the `OrgScoped` mixin and the settings DDL name the org table's pk.
    "apps/shared/persistence/base.py says 'organizations'",
    "apps/shared/settings/store.py says 'organizations'",
    # Postgres' own schema, not the `public` context — it predates the context by every migration.
    "apps/shared/settings/env.py says 'public'",
    # The shared shell links the account and operator surfaces of the foundation apps by URL.
    "apps/shared/templates/base.html says '/auth'",
    "apps/shared/templates/base.html says '/console'",
    "apps/shared/templates/base.html says '/profile'",
    "apps/shared/templates/errors/error.html says '/profile'",
}


# Strings through which something outside a demo names it — each a trace the demo's deletion
# would leave: a dead route, a table no longer there, a suite that no longer loads. Frozen by the
# string it spells; the list only shrinks, and `demo-apps-are-disposable` holds when it is empty.
_NAMES_A_DEMO = {
    # Organizations maps each app's entity to its detail route by name — the one production trace,
    # a hard-wired table where a registered surface belongs.
    "apps/organizations/contract/entity_links.py says '/calendar'",
    "apps/organizations/contract/entity_links.py says 'calendar'",
    "apps/organizations/contract/entity_links.py says 'files'",
    "apps/organizations/contract/entity_links.py says 'todo'",
    "apps/organizations/contract/entity_links.py says 'todos'",
    # The harness lists the demos' tables: the privilege books expect their grants, the worktree
    # test provisions a bucket per demo, the plugin list loads their steps.
    "tests/plugin.py says 'apps.calendar'",
    "tests/plugin.py says 'apps.files'",
    "tests/plugin.py says 'apps.learning'",
    "tests/plugin.py says 'apps.todo'",
    "tests/test_db_privileges.py says 'calendar_events'",
    "tests/test_db_privileges.py says 'card_states'",
    "tests/test_db_privileges.py says 'cards'",
    "tests/test_db_privileges.py says 'deck_subscriptions'",
    "tests/test_db_privileges.py says 'decks'",
    "tests/test_db_privileges.py says 'org_file_share_tokens'",
    "tests/test_db_privileges.py says 'org_files'",
    "tests/test_db_privileges.py says 'todos'",
    "tests/test_worktree.py says 'calendar'",
    # Scenarios of other apps, and the perf smoke, drive the todo demo to have something to act on.
    "apps/api_keys/tests/e2e/driver_mixin_api.py says 'todos'",
    "apps/api_keys/tests/e2e/driver_mixin_browser.py says 'todos'",
    "apps/api_keys/tests/e2e/steps.py says 'todos'",
    "apps/profile/tests/e2e/driver_mixin_api.py says 'todos'",
    "apps/profile/tests/e2e/driver_mixin_browser.py says 'todos'",
    "scripts/smoke.py says 'todos'",
    # Unit tests borrowing a demo's name as a sample app or route — the cheapest to repoint.
    "apps/issues/tests/test_capture.py says 'apps.todo'",
    "apps/shared/tests/test_capture.py says 'apps.todo'",
    "apps/shared/tests/test_log_chain.py says 'apps.todo'",
    "apps/shared/tests/test_loop_health.py says 'apps.todo'",
    "apps/shared/tests/test_request_logging.py says 'apps.todo'",
    "apps/timeline/tests/test_app_axis.py says 'apps.todo'",
    "apps/console/tests/test_console_styleguide.py says 'cards'",
    "apps/console/tests/test_events_catalogue.py says '/todo'",
    "apps/console/tests/test_live_settings.py says 'files'",
    "apps/console/tests/test_live_settings.py says 'todo'",
    "apps/issues/tests/test_capture.py says '/todo'",
    "apps/metrics/tests/test_accumulator.py says '/todo'",
    "apps/metrics/tests/test_service.py says '/todo'",
    "apps/organizations/tests/test_dashboard_activity.py says 'calendar'",
    "apps/organizations/tests/test_dashboard_activity.py says 'todo'",
    "apps/organizations/tests/test_entity_links.py says '/calendar'",
    "apps/organizations/tests/test_entity_links.py says 'calendar'",
    "apps/organizations/tests/test_entity_links.py says 'files'",
    "apps/organizations/tests/test_entity_links.py says 'learning'",
    "apps/organizations/tests/test_entity_links.py says 'todo'",
    "apps/organizations/tests/test_entity_links.py says 'todos'",
    "apps/profile/tests/test_recent_activity.py says 'todo'",
    "apps/shared/tests/test_activity.py says 'todo'",
    "apps/shared/tests/test_events.py says 'todo'",
    "apps/shared/tests/test_heavy_request.py says 'todos'",
    "apps/shared/tests/test_listener.py says 'calendar'",
    "apps/shared/tests/test_listener.py says 'files'",
    "apps/shared/tests/test_listener.py says 'learning'",
    "apps/shared/tests/test_listener.py says 'todo'",
    "apps/shared/tests/test_request_logging.py says '/todo'",
    "apps/shared/tests/test_request_logging.py says 'todos'",
    "apps/timeline/tests/test_app_axis.py says 'todo'",
    "apps/timeline/tests/test_entity_correlation.py says 'calendar'",
    "apps/timeline/tests/test_entity_correlation.py says 'todo'",
    "apps/timeline/tests/test_entity_naming.py says 'todo'",
    "apps/timeline/tests/test_paging.py says 'todo'",
    "apps/timeline/tests/test_pivots.py says 'todo'",
}


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
    failure either, which is why this is worth a test rather than a code review.

    The listed aliases are resolved to the modules they import, so an alias borrowed from another
    context still counts the module it really names; and the loop is asserted to be the *only*
    ``mount`` call site, so a stray mount outside it cannot stand in for a missing listing."""
    root = ast.parse((_APPS / "main.py").read_text())
    integration_of = {
        alias.asname or alias.name: (node.module or "")
        .removeprefix("apps.")
        .removesuffix(".contract")
        for node in ast.walk(root)
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith(".contract")
        for alias in node.names
        if alias.name == "integration"
    }
    mounted_tuple = next(
        node.value
        for node in root.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "_apps" for target in node.targets)
    )

    # `_apps = sorted((…), key=…)`: the mounted contexts are the sorted call's first argument,
    # not its key function.
    listed = mounted_tuple.args[0] if isinstance(mounted_tuple, ast.Call) else mounted_tuple

    mounted = {
        integration_of[node.id]
        for node in ast.walk(listed)
        if isinstance(node, ast.Name) and node.id in integration_of
    }
    mount_calls = [
        node.func.value.id
        for node in ast.walk(root)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "mount"
        and isinstance(node.func.value, ast.Name)
    ]

    assert (mounted, mount_calls) == (_contexts() | {"shared"}, ["_app"])


def test_the_shared_foundation_is_forbidden_from_every_context():
    """Two contracts carry the README's sentence, and both are asserted by content rather than by
    name: an emptied forbidden list, a narrowed source or a quiet `ignore_imports` entry would
    leave the contract's name standing while the boundary is gone. The context list is also what
    keeps a new app inside the boundary — the one place it is opt-in."""
    shared = _contract_named("shared imports no bounded context")
    domain = _contract_named("domain never imports infra")

    forbidden = {module.removeprefix("apps.") for module in shared["forbidden_modules"]}

    assert (
        forbidden,
        shared["source_modules"],
        shared.get("ignore_imports", []),
        domain["source_modules"],
        domain["forbidden_modules"],
        domain.get("ignore_imports", []),
    ) == (_contexts(), ["apps.shared"], [], ["apps.*.domain"], ["apps.*.infra"], [])


def _internal_modules(context: str) -> set[str]:
    """Everything importable in a context except its public contract — and its tests, which the
    allowed-importers clause scopes on its own."""
    return {
        f"apps.{context}.{child.stem}"
        for child in (_APPS / context).iterdir()
        if not child.name.startswith("__")
        and child.name not in {"contract", "tests", "templates"}
        and (child.is_dir() or child.suffix == ".py")
    }


def test_every_context_keeps_its_internals_private():
    """One `protected` contract per context, and not an emptied one: what each protects is derived
    from the context's own tree — every python child but `contract/` — and the only importers
    allowed are the context itself and test code. A contract drifting from the tree (a new package
    nobody protected, an `allowed_importers` widened to everyone) fails here, not in review."""
    protections = {
        contract["name"].removesuffix(" internals are private"): (
            set(contract["protected_modules"]),
            contract["allowed_importers"],
        )
        for contract in _contracts()
        if contract["type"] == "protected"
    }

    expected = {
        name: (_internal_modules(name), [f"apps.{name}.**", "apps.*.tests.**"])
        for name in _contexts()
    }

    assert protections == expected


def test_the_one_way_edge_out_of_auth_is_contracted():
    """The README names this edge specifically as the example of import-downward-event-upward —
    and an `ignore_imports` entry is how a real import gets waved through while the linter still
    reports the contract KEPT, so its absence is part of what is asserted."""
    contract = _contract_named("auth is a foundation: it never imports the organizations context")

    assert (
        contract["source_modules"],
        contract["forbidden_modules"],
        contract["type"],
        contract.get("ignore_imports", []),
    ) == (["apps.auth"], ["apps.organizations"], "forbidden", [])


def _context_tables() -> set[str]:
    """Every table owned by a bounded context — a shared SQL literal naming one is an import the
    linter cannot see."""
    tables = set()
    for mapper in Base.registry.mappers:
        if not mapper.class_.__module__.startswith("apps.shared"):
            tables |= {table.name for table in mapper.tables if isinstance(table, Table)}
    return tables


def _naming_tokens(text: str, contexts: set[str], tables: set[str]) -> set[str]:
    """How one string can name a context: its bare name, a path whose segment is one (`/auth/…`),
    a dotted module path into it (`apps.auth…`, a plugin list or a patch target), or a
    context-owned table spelled into SQL."""
    names = "|".join(sorted(contexts))
    tokens = {text} if text in contexts else set()
    tokens |= {f"/{hit}" for hit in re.findall(rf"/({names})(?=[/?\"' ]|$)", text)}
    tokens |= {f"apps.{hit}" for hit in re.findall(rf"\bapps\.({names})\b", text)}
    tokens |= set(re.findall(rf"\b({'|'.join(sorted(tables))})\b", text))
    return tokens


def _strings_naming(contexts: set[str], tables: set[str], paths) -> set[str]:
    """Every non-docstring string literal in ``paths`` that names one of ``contexts`` — by its bare
    name, by a URL pointing into it, or by one of ``tables``."""
    found = set()
    for path in paths:
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
                and id(node) not in docstrings
            ):
                found |= {
                    f"{relative} says {token!r}"
                    for token in _naming_tokens(node.value, contexts, tables)
                }
    return found


def _shared_strings_naming_a_context() -> set[str]:
    """Every non-docstring string literal under `apps/shared` that names a context."""
    return _strings_naming(
        _contexts(),
        _context_tables(),
        (
            path
            for path in sorted((_APPS / "shared").rglob("*.py"))
            if "/tests/" not in path.as_posix()
        ),
    )


def _shared_templates_naming_a_context() -> set[str]:
    """The same walk over the shared layout: a template is an inter-app surface import-linter
    cannot see, so a context named in one survives that context's deletion as a dead link."""
    contexts = sorted(_contexts())
    reference = re.compile(rf"/({'|'.join(contexts)})(?=[/?\"' ]|$)|[\"']({'|'.join(contexts)})/")
    found = set()
    for path in sorted((_APPS / "shared" / "templates").rglob("*.html")):
        prose_stripped = re.sub(r"\{#.*?#\}", "", path.read_text(), flags=re.DOTALL)
        relative = str(path.relative_to(_ROOT))
        found |= {
            f"{relative} says {f'/{hit[0]}' if hit[0] else f'{hit[1]}/'!r}"
            for hit in reference.findall(prose_stripped)
        }
    return found


def test_no_shared_module_names_a_bounded_context():
    """The whole "delete an app and nothing is left behind" promise rests here.

    import-linter already forbids shared *importing* a context; a string is how the rule gets
    broken without one — a settings key, a nav slug, a URL, a table spelled into SQL, a template
    path. Each one survives the app's deletion as a dangling reference to something that no
    longer exists, which is exactly the trace the README says cannot remain. What shared does
    name is frozen above, each with the reason it may.
    """
    named = _shared_strings_naming_a_context() | _shared_templates_naming_a_context()

    assert named == _NAMED_ON_PURPOSE


def _outside_the_demos() -> list[Path]:
    """Every Python module a demo's deletion leaves standing: the other apps with their tests, the
    harness, the scripts. The composition root, whose job is to mount every app, and this package,
    which reads the demos to hold the README's word on them, are left out."""
    demos = _demos()
    return [
        path
        for root in (_APPS, _ROOT / "tests", _ROOT / "scripts")
        for path in sorted(root.rglob("*.py"))
        if path != _APPS / "main.py"
        and not path.is_relative_to(Path(__file__).parent)
        and not (path.is_relative_to(_APPS) and path.relative_to(_APPS).parts[0] in demos)
    ]


def _demo_tables() -> set[str]:
    demos = _demos()
    return {
        table.name
        for mapper in Base.registry.mappers
        if mapper.class_.__module__.split(".")[1:2] in ([demo] for demo in demos)
        for table in mapper.tables
        if isinstance(table, Table)
    }


def test_nothing_outside_a_demo_names_it():
    """`apps/shared` naming a context is one trace; a demo named by another app, by the harness or
    by a script is the same trace one directory over — and deleting the demo turns each into a dead
    route, a missing table or a suite that no longer loads. What still names one is frozen here, by
    the string it spells; the list only shrinks, and at zero a demo is deleted without a trace."""
    named = _strings_naming(_demos(), _demo_tables(), _outside_the_demos())

    assert named == _NAMES_A_DEMO


def _contexts_providing(query_type: type) -> set[str]:
    """The contexts behind the mounted providers of one query type — the registry the request
    path reads, not the source that once registered them."""
    return {
        provider.__module__.split(".")[1]
        for provider in apps.main.host.contribs.providers(query_type)
    }


def test_every_context_declares_its_console_tile():
    """The tile is what makes an app visible to an admin — and what lets a *disabled* one be
    switched back on, since it registers before the enabled gate. Read off the mounted registry:
    a registration deleted from the manifest keeps the query's name in its dead provider, which
    is exactly what a source grep kept counting."""
    assert _contexts_providing(ConsoleOverviewQuery) == _contexts()


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


def _todo_surfaces(host: Host) -> dict[str, bool]:
    return {
        "routes": any("/todos" in path for path in host.app.openapi()["paths"]),
        "nav": bool(host.nav_items),
        "dashboard card": bool(host.contribs.providers(OverviewQuery)),
        "console tile": bool(host.contribs.providers(ConsoleOverviewQuery)),
    }


def test_a_disabled_app_drops_everything_but_its_console_tile(monkeypatch: pytest.MonkeyPatch):
    """The reference app mounted twice, on and off, and the two hosts compared surface by
    surface — the README's whole sentence in one table. The settings store is doubled (our own
    module) because the off state is a console decision this test has no console to make; both
    mounts run on the same code path the composition root uses."""
    monkeypatch.setattr("apps.shared.settings.store.seed_values", lambda app, defaults: None)
    saved = live.get_settings("todo").snapshot()
    monkeypatch.setattr("apps.shared.settings.live.seed_values", lambda app, defaults: None)

    monkeypatch.setattr("apps.shared.settings.live.read_values", lambda app: dict(saved))
    enabled_host = Host()
    todo_integration.mount(enabled_host)

    monkeypatch.setattr(
        "apps.shared.settings.live.read_values", lambda app: {**saved, "enabled": "false"}
    )
    disabled_host = Host()
    todo_integration.mount(disabled_host)

    live.get_settings("todo").restore(saved)

    assert (_todo_surfaces(enabled_host), _todo_surfaces(disabled_host)) == (
        {"routes": True, "nav": True, "dashboard card": True, "console tile": True},
        {"routes": False, "nav": False, "dashboard card": False, "console tile": True},
    )


def test_no_contract_exports_a_settings_handle():
    """Handlers take the app's settings *dependency* and get the request's effective values; a
    contract that exported the live handle instead would hand every consumer server-wide values
    with the org overrides silently dropped. So the handle never crosses a contract: calling
    ``get_settings`` inside a function is non-request code doing its job, but a module-level
    binding — or ``AppSettings`` in a contract's imports — is a handle exported."""
    exported = set()
    for path in sorted(_APPS.glob("*/contract/**/*.py")):
        relative = str(path.relative_to(_ROOT))
        tree = ast.parse(path.read_text())
        for statement in tree.body:
            if isinstance(statement, ast.Assign | ast.AnnAssign) and any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "get_settings"
                for node in ast.walk(statement)
            ):
                exported.add(f"{relative}:{statement.lineno} binds a handle at import time")
        exported |= {
            f"{relative}:{node.lineno} imports AppSettings"
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and any(alias.name == "AppSettings" for alias in node.names)
        }

    assert exported == set()


def test_the_contract_walk_actually_finds_the_modules():
    # Guards the guard: a glob that matched nothing would make the assertion above vacuous.
    assert len(list(_APPS.glob("*/contract/**/*.py"))) > 10


def test_the_reference_app_fills_every_surface():
    """`todo/` is what a new app is copied from, so a surface it stops demonstrating is a surface
    the next app will not have. The README lists them by name; this asks the *mounted* app for
    each one — a registration deleted from the manifest used to keep its spelling in the file,
    and a text grep counted it forever."""
    from apps.organizations.contract.events import OrganizationCreated
    from apps.shared.events.wiring import wiring

    filled = {
        "routes": any("/todos" in path for path in apps.main.app.openapi()["paths"]),
        "nav": any(item.match == "/todos" for item in apps.main.host.nav_items),
        "dashboard overview": "todo" in _contexts_providing(OverviewQuery),
        "console overview": "todo" in _contexts_providing(ConsoleOverviewQuery),
        "settings": live.get_settings("todo").declaration.defs != [],
        "feature switch": any(
            definition.key == "enabled" for definition in live.get_settings("todo").declaration.defs
        ),
        "seeding": "todo" in {r.app for r in wiring.consumers_of(OrganizationCreated)},
        "events": any(kind.startswith("todo.") for kind in catalog.kinds()),
        "api driver": (_APPS / "todo" / "tests" / "e2e" / "driver_mixin_api.py").exists(),
        "browser driver": (_APPS / "todo" / "tests" / "e2e" / "driver_mixin_browser.py").exists(),
    }

    missing = {name for name, present in filled.items() if not present}

    assert missing == set()


# The icon font shipped in `static/fonts/` is Phosphor's full regular set, but the CSS that names
# its glyphs is curated by hand — a surface may therefore declare an icon the stylesheet has no
# rule for, and the tile renders a blank square. Nothing fails, nothing logs; the tile is simply
# mute, which is precisely the kind of decay a declaration-level walk exists to catch.
_ICON_CSS = _ROOT / "static" / "css" / "input.css"


def _icons_with_a_rule() -> set[str]:
    return set(re.findall(r"\.ph\.ph-([a-z0-9-]+):before", _ICON_CSS.read_text()))


_ICON_DECLARED_RE = re.compile(
    r'icon(?::[^=\n]+)?\s*=\s*"([a-z0-9-]+)"'  # a call site, or a typed default: icon: ClassVar[…]
)


def _icons_declared() -> dict[str, str]:
    """Every ``icon="…"`` a surface passes, or declares as a typed default, mapped to where it
    says it. Tests aside: a fixture may name an icon nothing renders."""
    found = {}
    for path in sorted(_APPS.rglob("*.py")):
        if "/tests/" in path.as_posix():
            continue
        for icon in _ICON_DECLARED_RE.findall(path.read_text()):
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


def test_the_icon_walk_finds_a_classvar_default():
    # `icon: ClassVar[PhosphorIcon] = "shield-check"` — the annotated form every event class
    # uses, with no `icon="…"` call for the plain walk above to see.
    assert "shield-check" in _icons_declared()


def test_icon_declared_re_matches_a_plain_annotated_default():
    # `icon: str = "file-text"` — `OrgNavItem`'s shape: a typed default with no `ClassVar[…]`
    # wrapper, and no `icon="…"` call site of its own for the plain walk to see either.
    assert _ICON_DECLARED_RE.findall('icon: str = "file-text"') == ["file-text"]


def _icons_spelled_in_templates() -> dict[str, str]:
    """Every ``ph-<name>`` a template spells directly in its own markup, plus every quoted name a
    Jinja ternary in that slot picks between (``ph-{{ 'a' if … else 'b' }}``), mapped to where. A
    slot naming a bare variable (``ph-{{ icon }}``) contributes no name — there is nothing to
    read."""
    found = {}
    for path in sorted(_APPS.glob("*/templates/**/*.html")):
        text = path.read_text()
        site = str(path.relative_to(_ROOT))
        for icon in re.findall(r"\bph ph-([a-z0-9-]+)", text):
            found[icon] = site
        for expr in re.findall(r"\bph ph-\{\{(.*?)\}\}", text):
            # `'google-logo' if provider == 'google' else 'github-logo'` — only the ternary's two
            # branches name an icon; a quoted string inside its condition (``'google'`` above)
            # is a value being compared, not a glyph. Either quote style, matching Jinja itself.
            ternary = re.match(
                r"""\s*['"]([a-z0-9-]+)['"]\s+if\b.*\belse\s+['"]([a-z0-9-]+)['"]\s*$""", expr
            )
            if ternary:
                found[ternary.group(1)] = site
                found[ternary.group(2)] = site
    return found


def test_every_icon_a_template_spells_has_a_glyph_to_render():
    """A template that spells its own icon name never passes through `icon="…"`, so the walk
    above never sees it — the tile still goes mute the same way."""
    spelled = _icons_spelled_in_templates()

    with_rule = _icons_with_a_rule()

    mute = {f"{icon} ({site})" for icon, site in spelled.items() if icon not in with_rule}

    assert mute == set()


def test_the_template_icon_walk_finds_a_name_that_is_not_the_first_class():
    # `class="drag-handle ph ph-dots-six-vertical …"` — the icon class sits second, not first.
    assert "dots-six-vertical" in _icons_spelled_in_templates()


def test_the_template_icon_walk_actually_finds_the_names():
    # Guards the guard: a regex that matched nothing would make the assertion above vacuous.
    assert len(_icons_spelled_in_templates()) > 10


def test_the_template_icon_walk_finds_a_jinja_ternary_name():
    # `class="ph ph-{{ 'google-logo' if provider == 'google' else 'github-logo' }}"` — a name
    # picked at render time, not a bareword the plain walk above can read.
    assert {"google-logo", "github-logo"} <= _icons_spelled_in_templates().keys()


# A surface can also spell an icon as a literal character — ``▼``, ``▲``, ``✕``, ``↑``, ``✓``,
# a back arrow, a "goes to" arrow, or a caret pair — instead of reaching for the icon font. It
# renders the same to a sighted mouse user, but it is not `aria-hidden`-able the way an icon is,
# and it is not Phosphor. Jinja comments are stripped first, so prose that names the glyph —
# describing the affordance it used to be, as this file's own templates once did — is not
# mistaken for markup. A maintained set, grown as a violation turns up (issue #131 reported the
# first three, #148 the next two, #181 the last four) never frozen to one report. The last two,
# U+2039/U+203A, are spelled by code point rather than by character, so the source stays clear of
# the pair ruff's homoglyph check (RUF001) exists to flag.
_ICON_LOOKALIKE_GLYPHS = {"▲", "▼", "✕", "↑", "✓", "←", "→", chr(0x2039), chr(0x203A)}


def _template_markup_without_comments() -> dict[str, str]:
    return {
        str(path.relative_to(_ROOT)): re.sub(r"\{#.*?#\}", "", path.read_text(), flags=re.DOTALL)
        for path in _TEMPLATES
    }


def test_no_template_spells_an_icon_as_a_literal_glyph():
    bodies = _template_markup_without_comments()

    spelled = {
        f"{glyph!r} in {site}"
        for site, body in bodies.items()
        for glyph in _ICON_LOOKALIKE_GLYPHS
        if glyph in body
    }

    assert spelled == set()


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


# The strip paints a block by class: `bucket_blocks` emits a `kind`, the template renders it as
# `strip-<kind>`, and the stylesheet is what turns that into a colour. A kind the stylesheet never
# heard of draws a transparent block — a run that happened, on a lane that says it happened, with
# nothing on the film strip where it happened.


def test_every_band_the_strip_can_draw_has_a_colour():
    """The vocabulary is in one tuple (`_BAND_ORDER`); the colours are hand-written. Adding a state
    to the first without the second loses runs off the picture, silently."""
    painted = set(re.findall(r"\.strip-([a-z]+)\s*[,{]", _ICON_CSS.read_text()))

    assert {kind for kind, _ in BANDS} - painted == set()


def _mount_surfaces_imported_by(path: Path) -> set[str]:
    """The contexts whose ``contract/integration.py`` — the mount surface — this module imports,
    whether as a module (``from apps.todo.contract import integration``) or from inside it."""
    imported = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom):
            modules = [f"{node.module or ''}.{alias.name}" for alias in node.names]
        elif isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        else:
            continue
        for module in modules:
            parts = module.split(".")
            if parts[:1] == ["apps"] and parts[2:4] == ["contract", "integration"]:
                imported.add(parts[1])
    return imported


def test_the_composition_root_is_the_only_module_that_mounts():
    """ "The only place allowed to know several contexts at once: `main.py`" — a module knows a
    context by importing it, and a feature importing a foundation's *contract* is the healthy
    edge the README names two sections later. So the line is drawn at the mount surface: a second
    module importing a `contract/integration.py` is a second composition root, and the one there
    is imports every context's."""
    importers = {
        str(path.relative_to(_ROOT)): mounts
        for path in sorted(_APPS.rglob("*.py"))
        if "/tests/" not in path.as_posix() and (mounts := _mount_surfaces_imported_by(path))
    }

    assert importers == {"apps/main.py": _contexts() | {"shared"}}


# The two collaboration objects and the methods that key a handler on them. ``collect`` takes an
# instance and dispatches on its type, so it has nothing to annotate — it is walked for literals
# with the others.
_KEYED_REGISTRATIONS = {Contribs: ("provide",), EventBus: ("declare", "on", "spread")}
_COLLABORATION_METHODS = {"provide", "declare", "on", "spread", "collect"}


def _is_a_registry(receiver: ast.expr) -> bool:
    return ast.unparse(receiver).split(".")[-1] in {"events", "contribs"}


def test_the_collaboration_registries_are_keyed_by_type_alone():
    """ "Both key handlers by the Python type they carry, so there are no magic strings" — held
    at both ends. The host carries exactly the two objects; each registration parameter is
    annotated as a type, so a string is a type error; and no call site under `apps/` passes a
    literal where the type goes, which is the shape a string-keyed sibling would need."""
    collaborators = {
        name: hint
        for name, hint in typing.get_type_hints(Host).items()
        if hint in (EventBus, Contribs)
    }
    registrations = {
        f"{cls.__name__}.{method}": typing.get_origin(
            list(inspect.signature(getattr(cls, method)).parameters.values())[1].annotation
        )
        for cls, methods in _KEYED_REGISTRATIONS.items()
        for method in methods
    }
    literal_keys = {
        f"{path.relative_to(_ROOT)}:{node.lineno}"
        for path in sorted(_APPS.rglob("*.py"))
        if "/tests/" not in path.as_posix()
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _COLLABORATION_METHODS
        and _is_a_registry(node.func.value)
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }

    assert (collaborators, registrations, literal_keys) == (
        {"events": EventBus, "contribs": Contribs},
        {
            "Contribs.provide": type,
            "EventBus.declare": type,
            "EventBus.on": type,
            "EventBus.spread": type,
        },
        set(),
    )
