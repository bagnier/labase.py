"""AGENTS.md's conventions, checked on the code: a new exception costs an edit here."""

import ast
import re
import uuid
from pathlib import Path

import apps.main  # noqa: F401 — fills the ORM registry
from apps.shared.persistence.base import Base

_ROOT = Path(__file__).resolve().parents[2]
_APPS = _ROOT / "apps"

# The three session dependencies (`RlsSession` wraps the first, `AdminSession` the third) and
# their shared private helper.
_SESSION_PROVIDERS = {
    "apps/auth/infra/session.py::get_rls_session",
    "apps/shared/persistence/database.py::_session",
    "apps/shared/persistence/database.py::get_admin_session",
    "apps/shared/persistence/database.py::get_user_session",
}

# Link and settings tables keep composite keys: a surrogate id would be a second identity. The
# share token is a uuid4 (AGENTS: every key is a UUIDv7, every token a UUIDv4).
_NATURAL_COMPOSITE_KEYS = {"app_settings", "memberships", "org_app_settings"}
# A range-partitioned table is a different reason to be composite: Postgres requires the
# partition column in every unique key, so the key pairs it with the table's own uuid7 surrogate
# — named here, so that surrogate still owes uuid7 rather than skipping the check altogether.
_PARTITIONED_COMPOSITE_KEYS = {"log_lines": "ts"}
_RANDOM_TOKEN_KEYS = {"org_file_share_tokens"}


def _python_files(*roots: Path):
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            yield path, str(path.relative_to(_ROOT))


def test_the_session_dependencies_are_exactly_the_three_named():
    """Functions yielding an ``AsyncSession`` under ``apps/``."""
    providers = {
        f"{relative}::{node.name}"
        for path, relative in _python_files(_APPS)
        if "/tests/" not in relative
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.returns is not None
        and "AsyncGenerator[AsyncSession" in ast.unparse(node.returns)
    }

    assert providers == _SESSION_PROVIDERS


def _key_generator(column) -> object:
    """A pk column's default callable, unwrapped from SQLAlchemy's context wrapper."""
    generate = getattr(column.default, "arg", None)
    return getattr(generate, "__wrapped__", generate)


def test_every_mapped_primary_key_is_a_time_ordered_uuid7():
    """On every mapped table, not only the mixin. A partitioned table's surrogate `id` still
    owes uuid7, though its pair is exempt."""
    composite, tokens, strays = set(), set(), set()
    for table in Base.metadata.tables.values():
        keys = list(table.primary_key.columns)
        if len(keys) > 1:
            composite.add(table.name)
            partition_column = _PARTITIONED_COMPOSITE_KEYS.get(table.name)
            if partition_column is not None:
                surrogate = next(key for key in keys if key.name != partition_column)
                if _key_generator(surrogate) is not uuid.uuid7:
                    strays.add(f"{table.name}.{surrogate.name}")
        elif _key_generator(keys[0]) is uuid.uuid4:
            tokens.add(table.name)
        elif _key_generator(keys[0]) is not uuid.uuid7:
            strays.add(f"{table.name}.{keys[0].name}")

    assert (composite, tokens, strays) == (
        _NATURAL_COMPOSITE_KEYS | set(_PARTITIONED_COMPOSITE_KEYS),
        _RANDOM_TOKEN_KEYS,
        set(),
    )


# The columns that must stay uuid4.
_TOKEN_COLUMNS = {"org_file_share_tokens.token", "org_invitations.token"}


def test_the_uuid4_exception_is_exactly_the_token_columns():
    """Every token column defaults to uuid4, and no other column does."""
    defaulting_to_uuid4 = {
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if _key_generator(column) is uuid.uuid4
    }

    assert defaulting_to_uuid4 == _TOKEN_COLUMNS


def _assigned_attrs(target: ast.expr):
    if isinstance(target, ast.Tuple | ast.List):
        for elt in target.elts:
            yield from _assigned_attrs(elt)
    elif isinstance(target, ast.Attribute):
        yield target.attr


def test_no_repository_assigns_updated_at_from_the_python_clock():
    """A trigger sets ``updated_at`` on every update: a Python write of it is dead code."""
    offenders = {
        f"{relative}:{node.lineno}"
        for path, relative in _python_files(_APPS)
        if "/tests/" not in relative
        for node in ast.walk(ast.parse(path.read_text()))
        if (
            isinstance(node, ast.Assign)
            and any(
                attr == "updated_at" for target in node.targets for attr in _assigned_attrs(target)
            )
        )
        or (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "setattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "updated_at"
        )
    }

    assert offenders == set()


def test_templates_tests_and_steps_live_with_their_context():
    """A template, test or step module outside its context outlives the context's deletion."""
    misplaced = (
        {
            str(path.relative_to(_ROOT))
            for path in list(_APPS.rglob("steps.py")) + list((_ROOT / "tests").rglob("steps.py"))
            if not path.match("apps/*/tests/e2e/steps.py")
        }
        | {
            str(path.relative_to(_ROOT))
            for path in _APPS.rglob("templates")
            if path.is_dir() and not path.match("apps/*/templates")
        }
        | {
            relative
            for path, relative in _python_files(_APPS)
            if path.name.startswith("test_") and "/tests/" not in relative
        }
    )

    assert misplaced == set()


# A document starting with one of these loses its structure to the parser's foster-parenting.
_FOSTER_PARENTED = {"caption", "col", "colgroup", "tbody", "td", "tfoot", "th", "thead", "tr"}


def _fragment_responses() -> set[str]:
    """The ``_*.html`` returned as responses, not only included."""
    fragments = set()
    for path in sorted(_APPS.rglob("*.py")):
        if "/tests/" in path.as_posix():
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.endswith(".html")
                and Path(node.value).name.startswith("_")
            ):
                fragments.add(node.value)
    return fragments


def _first_rendered_tag(template: Path) -> str:
    """The first tag rendered, macro bodies aside."""
    body = template.read_text()
    body = re.sub(r"\{%-?\s*macro\b.*?\bendmacro\s*-?%\}", "", body, flags=re.DOTALL)
    body = re.sub(r"\{#.*?#\}", "", body, flags=re.DOTALL)
    tag = re.search(r"<([a-zA-Z][\w-]*)", body)
    return tag.group(1).lower() if tag else ""


def test_no_fragment_response_starts_inside_a_table():
    """(AGENTS: one set of helpers branches JSON, fragment and page) A fragment starting with
    table furniture parses into nothing on its own."""
    inside_a_table = {
        f"{name} starts with <{tag}>"
        for name in _fragment_responses()
        for template in _APPS.glob(f"*/templates/{name}")
        if (tag := _first_rendered_tag(template)) in _FOSTER_PARENTED
    }

    assert inside_a_table == set()


def test_the_fragment_walk_actually_finds_the_responses():
    # Guards the guard: a walk matching nothing would make it vacuous.
    assert len(_fragment_responses()) > 10


def _routers() -> list[Path]:
    """Every router module — not just the ones literally named ``router.py``
    (``accounts_router.py``, ``invitation_router.py``), plus the one app with no ``infra/``
    split. The same enumeration `_db_touches_in_routers` uses in test_ratchets.py."""
    return [*sorted(_APPS.glob("*/infra/*router*.py")), _APPS / "health" / "router.py"]


def _negotiation_header_offenders() -> set[str]:
    """Every router line reading ``HX-Request`` or ``Accept`` off ``request.headers`` by hand
    instead of through ``wants_json`` / ``is_htmx`` / ``wants_full_page`` — the single source
    of truth AGENTS.md names for that branch."""
    offenders = set()
    for path in _routers():
        relative = str(path.relative_to(_ROOT))
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Attribute)
                and node.func.value.attr == "headers"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
                and node.args[0].value.lower() in {"hx-request", "accept"}
            ):
                offenders.add(f"{relative}:{node.lineno}")
    return offenders


def test_no_router_reads_the_negotiation_headers_by_hand():
    """ "One set of helpers branches JSON, fragment and page" — a router re-spelling
    ``HX-Request`` or ``Accept`` by hand instead of calling ``wants_json`` / ``is_htmx`` /
    ``wants_full_page`` passes the rest of the suite the same way the four routers #130 fixed
    did before that fix."""
    assert _negotiation_header_offenders() == set()


def test_the_router_walk_actually_finds_the_files():
    # Guards the guard: a walk that matched nothing would make the assertion above vacuous.
    assert len(_routers()) > 10


def test_the_layout_walk_actually_finds_the_files():
    # Guards the guard: globs matching nothing would make it vacuous.
    steps = list(_APPS.rglob("steps.py"))

    template_roots = [path for path in _APPS.rglob("templates") if path.is_dir()]

    assert (len(steps) > 10, len(template_roots) > 10) == (True, True)


def _status_access(node: ast.expr) -> bool:
    """``x.status`` or ``x["status"]``."""
    if isinstance(node, ast.Attribute) and node.attr == "status":
        return True
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == "status"
    )


def _string_literals(node: ast.expr) -> list[ast.Constant]:
    """A literal, or the literals of a set, tuple or list tested with ``in``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node]
    if isinstance(node, ast.Set | ast.Tuple | ast.List):
        return [
            element
            for element in node.elts
            if isinstance(element, ast.Constant) and isinstance(element.value, str)
        ]
    return []


def test_invitation_status_is_never_compared_to_a_bare_string():
    """Against a literal, ``"revokd"`` passes ``ty``; against ``InvitationStatus``, it fails
    (AGENTS: invariants are types, not checks)."""
    path = _APPS / "organizations" / "infra" / "invitation_router.py"
    offenders = {
        node.lineno
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Compare)
        and any(_status_access(side) for side in [node.left, *node.comparators])
        and any(_string_literals(side) for side in [node.left, *node.comparators])
    }

    assert offenders == set()
