"""Every app mounts alike and leaves no trace when deleted (AGENTS: an app declares every surface
it contributes). Checked on declarations: manifests, the composition root, import-linter contracts.
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
from apps.console.infra import router as console_router
from apps.issues.contract.events import IssueOpened, IssueRegressed
from apps.organizations.contract.overviews import OverviewQuery
from apps.shared.events import BusinessEvent
from apps.shared.events.bus import EventBus
from apps.shared.events.catalog import catalog
from apps.shared.integration.contribs import Contribs
from apps.shared.integration.host import Host, NavItem
from apps.shared.logs.capture import ExceptionCaptured
from apps.shared.persistence.base import Base
from apps.shared.settings import live
from apps.tasks.domain.strip import BANDS
from apps.todo.contract import integration as todo_integration
from tests.meta.test_ratchets import _demos

_ROOT = Path(__file__).resolve().parents[2]
_APPS = _ROOT / "apps"

# Strings by which `apps/shared` names a context on purpose, each with its reason.
_NAMED_ON_PURPOSE = {
    # The journal writer pins the actor's and org's names onto each fact.
    "apps/shared/events/repository.py says 'organizations'",
    "apps/shared/events/repository.py says 'profiles'",
    # The 401 handler redirects to auth's sign-in.
    "apps/shared/http/exceptions.py says '/auth'",
    # The request logger knows health's probe paths.
    "apps/shared/logs/request.py says '/health'",
    # Multi-tenancy: `OrgScoped` and the settings tables reference organizations.
    "apps/shared/persistence/base.py says 'organizations'",
    "apps/shared/settings/store.py says 'organizations'",
    # Postgres's schema, not the context.
    "apps/shared/settings/env.py says 'public'",
    # The shared shell links the foundation apps' pages.
    "apps/shared/templates/base.html says '/auth'",
    "apps/shared/templates/base.html says '/console'",
    "apps/shared/templates/base.html says '/profile'",
    "apps/shared/templates/errors/error.html says '/profile'",
}


# Strings naming a demo outside it, each a trace its deletion would leave. Empty, the
# `demo-apps-are-disposable` claim holds.
_NAMES_A_DEMO = {
    # Entity links, hard-wired by app name: the one production trace.
    "apps/organizations/contract/entity_links.py says '/calendar'",
    "apps/organizations/contract/entity_links.py says 'calendar'",
    "apps/organizations/contract/entity_links.py says 'files'",
    "apps/organizations/contract/entity_links.py says 'todo'",
    "apps/organizations/contract/entity_links.py says 'todos'",
    # The harness: privilege expectations, the worktree test, the steps plugin list.
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
    # Other apps' scenarios and the perf smoke act on todos.
    "apps/api_keys/tests/e2e/driver_mixin_api.py says 'todos'",
    "apps/api_keys/tests/e2e/driver_mixin_browser.py says 'todos'",
    "apps/api_keys/tests/e2e/steps.py says 'todos'",
    "apps/profile/tests/e2e/driver_mixin_api.py says 'todos'",
    "apps/profile/tests/e2e/driver_mixin_browser.py says 'todos'",
    "scripts/smoke.py says 'todos'",
    # Unit tests borrowing a demo as a sample.
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
    return {
        path.name
        for path in _APPS.iterdir()
        if (path / "__init__.py").exists() and path.name != "shared"
    }


def _module_names(path: Path) -> set[str]:
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
    """``contract/integration.py`` with ``mount`` and ``PHASE``, all the composition root uses."""
    incomplete = {
        name
        for name in _contexts()
        if not (integration := _APPS / name / "contract" / "integration.py").exists()
        or not {"mount", "PHASE"} <= _module_names(integration)
    }

    assert incomplete == set()


def test_the_composition_root_mounts_every_context():
    """An unmounted app ships dead, silently. Aliases are resolved to their modules, and the loop
    is the only ``mount`` call."""
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

    # `_apps = sorted((…), key=…)`: the first argument.
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
    """Checked by content, not name: an emptied list or an `ignore_imports` entry would keep the
    name and lose the boundary."""
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
    """A context's modules but its contract and tests."""
    return {
        f"apps.{context}.{child.stem}"
        for child in (_APPS / context).iterdir()
        if not child.name.startswith("__")
        and child.name not in {"contract", "tests", "templates"}
        and (child.is_dir() or child.suffix == ".py")
    }


def test_every_context_keeps_its_internals_private():
    """One `protected` contract per context, matching its tree (everything but `contract/`), with
    only itself and tests as importers."""
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
    """(AGENTS: import downward, event upward) No `ignore_imports` entry either, which would
    keep the contract KEPT."""
    contract = _contract_named("auth is a foundation: it never imports the organizations context")

    assert (
        contract["source_modules"],
        contract["forbidden_modules"],
        contract["type"],
        contract.get("ignore_imports", []),
    ) == (["apps.auth"], ["apps.organizations"], "forbidden", [])


def _context_tables() -> set[str]:
    """Tables owned by a context: SQL naming one is an import the linter cannot see."""
    tables = set()
    for mapper in Base.registry.mappers:
        if not mapper.class_.__module__.startswith("apps.shared"):
            tables |= {table.name for table in mapper.tables if isinstance(table, Table)}
    return tables


def _naming_tokens(text: str, contexts: set[str], tables: set[str]) -> set[str]:
    """By its name, a path segment (`/auth/…`), a module path (`apps.auth…`) or one of its
    tables."""
    names = "|".join(sorted(contexts))
    tokens = {text} if text in contexts else set()
    tokens |= {f"/{hit}" for hit in re.findall(rf"/({names})(?=[/?\"' ]|$)", text)}
    tokens |= {f"apps.{hit}" for hit in re.findall(rf"\bapps\.({names})\b", text)}
    tokens |= set(re.findall(rf"\b({'|'.join(sorted(tables))})\b", text))
    return tokens


def _strings_naming(contexts: set[str], tables: set[str], paths) -> set[str]:
    """Non-docstring strings in ``paths`` naming one of ``contexts``."""
    found = set()
    for path in paths:
        tree = ast.parse(path.read_text())
        # Docstrings, by identity: prose may name a context.
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
    """Shared templates: a context named there survives as a dead link."""
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
    """A string (settings key, slug, URL, SQL table, template path) breaks the boundary
    import-linter guards, and survives the app as a dangling reference."""
    named = _shared_strings_naming_a_context() | _shared_templates_naming_a_context()

    assert named == _NAMED_ON_PURPOSE


def _outside_the_demos() -> list[Path]:
    """Modules a demo's deletion leaves, but the composition root and this package."""
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
    """Another app, the harness or a script naming a demo: frozen above."""
    named = _strings_naming(_demos(), _demo_tables(), _outside_the_demos())

    assert named == _NAMES_A_DEMO


def _contexts_providing(query_type: type) -> set[str]:
    """The contexts of the mounted providers of ``query_type``."""
    return {
        provider.__module__.split(".")[1]
        for provider in apps.main.host.contribs.providers(query_type)
    }


def test_every_context_declares_its_console_tile():
    """The tile lets an admin switch a disabled app back on. Read from the mounted registry, not
    the source."""
    assert _contexts_providing(ConsoleOverviewQuery) == _contexts()


def _writes_under(package: str) -> set[str]:
    """Sites that could write: a fact emitted, a row given to a session (not a set's ``add``), a
    DML import."""
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
    assert _writes_under("timeline") == set()


def _keywords_passed_to(class_name: str) -> set[str]:
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
    """The journal is readable by whom it names: the issue would show in their feed."""
    named = {
        f"{cls.__name__}(user_id=…)"
        for cls in (IssueOpened, IssueRegressed)
        if "user_id" in _keywords_passed_to(cls.__name__)
    }

    assert named == set()


def test_the_capture_seam_is_not_a_business_fact():
    """`ExceptionCaptured` goes straight to the trackers, never on the journal."""
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
    """The reference app mounted on and off, surface by surface. The settings store is doubled
    to switch it off."""
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
    """An exported handle would drop org overrides. A module-level binding or an ``AppSettings``
    import in a contract exports one; a call inside a function does not."""
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
    """`todo/` is copied by new apps: each surface the README lists, asked of the mounted app."""
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


# The icon CSS is curated by hand: an icon without a rule renders an empty square, silently.
_ICON_CSS = _ROOT / "static" / "css" / "input.css"


def _icons_with_a_rule() -> set[str]:
    return set(re.findall(r"\.ph\.ph-([a-z0-9-]+):before", _ICON_CSS.read_text()))


_ICON_DECLARED_RE = re.compile(
    r'icon(?::[^=\n]+)?\s*=\s*"([a-z0-9-]+)"'  # a call, or a typed default
)


def _icons_declared() -> dict[str, str]:
    """Each ``icon="…"`` or typed default outside tests, with where it is — plus ``_GROUP_DISPLAY``'s
    and every mounted ``NavItem``'s, read from the live objects rather than pattern-matched: neither
    carries an ``icon`` word anywhere near its value."""
    found = {}
    for path in sorted(_APPS.rglob("*.py")):
        if "/tests/" in path.as_posix():
            continue
        for icon in _ICON_DECLARED_RE.findall(path.read_text()):
            found[icon] = str(path.relative_to(_ROOT))

    router_site = str(Path(inspect.getfile(console_router)).relative_to(_ROOT))
    for _title, icon, _section in console_router._GROUP_DISPLAY.values():
        found[icon] = router_site

    nav_item_site = str(Path(inspect.getfile(NavItem)).relative_to(_ROOT))
    for item in apps.main.host.nav_items:
        found[item.icon] = nav_item_site
    return found


def test_every_icon_a_surface_declares_has_a_glyph_to_render():
    declared = _icons_declared()

    with_rule = _icons_with_a_rule()

    mute = {f"{icon} ({site})" for icon, site in declared.items() if icon not in with_rule}

    assert mute == set()


def test_the_icon_walk_actually_finds_the_declarations():
    # Guards the guard: a regex that matched nothing would make the assertion above vacuous.
    assert len(_icons_declared()) > 10


def test_the_icon_walk_finds_a_classvar_default():
    # `icon: ClassVar[PhosphorIcon] = "shield-check"`, as event classes declare it.
    assert "shield-check" in _icons_declared()


def test_icon_declared_re_matches_a_plain_annotated_default():
    # `icon: str = "file-text"`, as `OrgNavItem` declares it.
    assert _ICON_DECLARED_RE.findall('icon: str = "file-text"') == ["file-text"]


def test_the_icon_walk_finds_a_name_declared_in_a_plain_tuple():
    # `_GROUP_DISPLAY`'s `(title, icon, section)` tuple names an icon with no `icon` word nearby.
    assert "gear-six" in _icons_declared()


def test_the_icon_walk_finds_an_icon_passed_positionally_to_a_nav_item():
    # `NavItem("Pages", "note-pencil", "pages", "/pages", order=40)`: the same plain-tuple shape,
    # and unlike `_GROUP_DISPLAY`'s "gear-six" this name is declared nowhere else either.
    assert "note-pencil" in _icons_declared()


def _icons_spelled_in_templates() -> dict[str, str]:
    """Each ``ph-<name>`` in templates, and both names of a ``ph-{{ 'a' if … else 'b' }}``; a
    bare variable gives none."""
    found = {}
    for path in sorted(_APPS.glob("*/templates/**/*.html")):
        text = path.read_text()
        site = str(path.relative_to(_ROOT))
        for icon in re.findall(r"\bph ph-([a-z0-9-]+)", text):
            found[icon] = site
        for expr in re.findall(r"\bph ph-\{\{(.*?)\}\}", text):
            # The branches, not the condition's ``'google'``; either quote style.
            ternary = re.match(
                r"""\s*['"]([a-z0-9-]+)['"]\s+if\b.*\belse\s+['"]([a-z0-9-]+)['"]\s*$""", expr
            )
            if ternary:
                found[ternary.group(1)] = site
                found[ternary.group(2)] = site
    return found


def test_every_icon_a_template_spells_has_a_glyph_to_render():
    spelled = _icons_spelled_in_templates()

    with_rule = _icons_with_a_rule()

    mute = {f"{icon} ({site})" for icon, site in spelled.items() if icon not in with_rule}

    assert mute == set()


def test_the_template_icon_walk_finds_a_name_that_is_not_the_first_class():
    # `class="drag-handle ph ph-dots-six-vertical …"`: not the first class.
    assert "dots-six-vertical" in _icons_spelled_in_templates()


def test_the_template_icon_walk_actually_finds_the_names():
    # Guards the guard: a regex that matched nothing would make the assertion above vacuous.
    assert len(_icons_spelled_in_templates()) > 10


def test_the_template_icon_walk_finds_a_jinja_ternary_name():
    # `class="ph ph-{{ 'google-logo' if provider == 'google' else 'github-logo' }}"`.
    assert {"google-logo", "github-logo"} <= _icons_spelled_in_templates().keys()


# Glyphs written as characters instead of Phosphor icons, which can be `aria-hidden`. Jinja
# comments are stripped first. The set grows with each case found; U+2039/U+203A are code points,
# clear of ruff's homoglyph check (RUF001).
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


# ``data-hash-tabs`` needs its script; without it, tabs still switch but lose reloads and links.
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


# Each band is coloured by a `strip-<kind>` CSS rule; without one, the block is invisible.


def test_every_band_the_strip_can_draw_has_a_colour():
    painted = set(re.findall(r"\.strip-([a-z]+)\s*[,{]", _ICON_CSS.read_text()))

    assert {kind for kind, _ in BANDS} - painted == set()


def _mount_surfaces_imported_by(path: Path) -> set[str]:
    """Contexts whose ``contract/integration.py`` this module imports, either way."""
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
    """A module importing a ``contract/integration.py`` is a second composition root."""
    importers = {
        str(path.relative_to(_ROOT)): mounts
        for path in sorted(_APPS.rglob("*.py"))
        if "/tests/" not in path.as_posix() and (mounts := _mount_surfaces_imported_by(path))
    }

    assert importers == {"apps/main.py": _contexts() | {"shared"}}


# The methods keying handlers by type; ``collect`` takes an instance, walked for literals only.
_KEYED_REGISTRATIONS = {Contribs: ("provide",), EventBus: ("declare", "on", "spread")}
_COLLABORATION_METHODS = {"provide", "declare", "on", "spread", "collect"}


def _is_a_registry(receiver: ast.expr) -> bool:
    return ast.unparse(receiver).split(".")[-1] in {"events", "contribs"}


def test_the_collaboration_registries_are_keyed_by_type_alone():
    """(AGENTS: two collaboration objects, two shapes) Parameters typed as types, and no call
    passing a literal there."""
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
