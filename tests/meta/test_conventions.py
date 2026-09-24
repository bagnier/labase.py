"""Conventions the README states as absolutes, checked from the artefact rather than its prose.

Each of these decays one exception at a time — a fourth session dependency, a serial key, a test
module parked next to the router it tests — and no single exception breaks anything the day it
lands. The walks below make the first exception cost an edit here, which is the decision the
README says someone has to make.
"""

import ast
import re
import uuid
from pathlib import Path

import apps.main  # noqa: F401 — mounting every app fills the ORM registry with every model
from apps.shared.persistence.base import Base

_ROOT = Path(__file__).resolve().parents[2]
_APPS = _ROOT / "apps"

# The three dependencies the README names — `RlsSession` wraps the first, `AdminSession` the
# third — plus the private substrate the two raw ones share. A fifth entry here is the "real
# decision" the claim's waiver said would announce itself nowhere; now it announces itself here.
_SESSION_PROVIDERS = {
    "apps/auth/infra/session.py::get_rls_session",
    "apps/shared/persistence/database.py::_session",
    "apps/shared/persistence/database.py::get_admin_session",
    "apps/shared/persistence/database.py::get_user_session",
}

# Link and settings tables keep their natural composite keys — a surrogate id on a row that *is*
# its pair would be a second identity to keep unique. The share token is the README's own stated
# exception: a security token stays a random uuid4, unguessable, with no timestamp to read off it.
_NATURAL_COMPOSITE_KEYS = {"app_settings", "memberships", "org_app_settings"}
_RANDOM_TOKEN_KEYS = {"org_file_share_tokens"}


def _python_files(*roots: Path):
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            yield path, str(path.relative_to(_ROOT))


def test_the_session_dependencies_are_exactly_the_three_named():
    """A DB session provider is a function yielding an ``AsyncSession`` — the shape FastAPI
    injects. Enumerated over ``apps/`` so a fourth kind of session cannot appear quietly."""
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
    """The Python callable a pk column defaults to — unwrapped, since SQLAlchemy wraps a
    zero-argument callable to feed it the execution context."""
    generate = getattr(column.default, "arg", None)
    return getattr(generate, "__wrapped__", generate)


def test_every_mapped_primary_key_is_a_time_ordered_uuid7():
    """ "Every primary key is a time-ordered UUIDv7" — walked over every mapped table, not proven
    on the mixin alone. The two exception families are frozen above, so a new composite key or a
    new token is an edit here, made on purpose."""
    composite, tokens, strays = set(), set(), set()
    for table in Base.metadata.tables.values():
        keys = list(table.primary_key.columns)
        if len(keys) > 1:
            composite.add(table.name)
        elif _key_generator(keys[0]) is uuid.uuid4:
            tokens.add(table.name)
        elif _key_generator(keys[0]) is not uuid.uuid7:
            strays.add(f"{table.name}.{keys[0].name}")

    assert (composite, tokens, strays) == (_NATURAL_COMPOSITE_KEYS, _RANDOM_TOKEN_KEYS, set())


# The security tokens, named: the columns that must stay uuid4 — unguessable, with no timestamp
# to read off them. `test_every_mapped_primary_key_is_a_time_ordered_uuid7` already keeps uuid4
# out of the primary keys; this is the other direction.
_TOKEN_COLUMNS = {"org_file_share_tokens.token", "org_invitations.token"}


def test_the_uuid4_exception_is_exactly_the_token_columns():
    """ "Security tokens are the deliberate exception — they stay random UUIDv4", checked both
    ways now that the exception has a list: every token column defaults to uuid4, and no other
    column does."""
    defaulting_to_uuid4 = {
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if _key_generator(column) is uuid.uuid4
    }

    assert defaulting_to_uuid4 == _TOKEN_COLUMNS


def _assigned_attrs(target: ast.expr):
    """Flatten a (possibly tuple/list-unpacking) assignment target into the attributes it sets."""
    if isinstance(target, ast.Tuple | ast.List):
        for elt in target.elts:
            yield from _assigned_attrs(elt)
    elif isinstance(target, ast.Attribute):
        yield target.attr


def test_no_repository_assigns_updated_at_from_the_python_clock():
    """Every ``Timestamped`` table's ``before update`` trigger overwrites ``updated_at`` on the
    way in regardless of what the statement sent, so a repository writing it from Python
    alongside — whether a plain assignment, an unpacked one, or a ``setattr`` — is dead code on
    that path, only ever read back as the trigger's own Postgres ``now()``."""
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
    """The layout half of self-containment: a template, a test or a step module parked outside
    its context is the piece a deletion leaves behind."""
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


# What a browser's parser refuses to keep outside its context: handed a document that *starts*
# with one of these, it foster-parents the text and drops the structure — 0 rows, 0 cells.
_FOSTER_PARENTED = {"caption", "col", "colgroup", "tbody", "td", "tfoot", "th", "thead", "tr"}


def _fragment_responses() -> set[str]:
    """Every ``_*.html`` a python module returns as a response — the fragments that really are
    "swapped into the live DOM", as opposed to partials only ever included by other templates."""
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
    """The first HTML tag the template renders — macro bodies stripped, since a macro defined at
    the top is not output until something below calls it."""
    body = template.read_text()
    body = re.sub(r"\{%-?\s*macro\b.*?\bendmacro\s*-?%\}", "", body, flags=re.DOTALL)
    body = re.sub(r"\{#.*?#\}", "", body, flags=re.DOTALL)
    tag = re.search(r"<([a-zA-Z][\w-]*)", body)
    return tag.group(1).lower() if tag else ""


def test_no_fragment_response_starts_inside_a_table():
    """ "Fragments are standalone valid markup (they're swapped into the live DOM)" — held on the
    half a parser can refuse: a fragment whose first element is table furniture only survives
    inside the right ancestor, and parsed alone it foster-parents into nothing. The rest of the
    sentence (well-formedness at large) stays a review question."""
    inside_a_table = {
        f"{name} starts with <{tag}>"
        for name in _fragment_responses()
        for template in _APPS.glob(f"*/templates/{name}")
        if (tag := _first_rendered_tag(template)) in _FOSTER_PARENTED
    }

    assert inside_a_table == set()


def test_the_fragment_walk_actually_finds_the_responses():
    # Guards the guard: a walk that matched nothing would make the assertion above vacuous.
    assert len(_fragment_responses()) > 10


def test_the_layout_walk_actually_finds_the_files():
    # Guards the guard: globs that matched nothing would make the assertion above vacuous.
    steps = list(_APPS.rglob("steps.py"))

    template_roots = [path for path in _APPS.rglob("templates") if path.is_dir()]

    assert (len(steps) > 10, len(template_roots) > 10) == (True, True)


def test_get_invitation_by_token_returns_a_typed_model():
    """ "Invariants are types, not checks": the repository read comes back as ``InvitationRead``,
    not a bare ``dict`` — the shape that let a status be indexed and compared as an untyped
    string in the first place."""
    path = _APPS / "organizations" / "infra" / "repository.py"
    fn = next(
        node
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_invitation_by_token"
    )

    assert fn.returns is not None
    assert ast.unparse(fn.returns) == "InvitationRead | None"


def _status_access(node: ast.expr) -> bool:
    """``x.status`` or ``x["status"]`` — the two shapes an invitation's status is read as,
    whether it arrives typed or as a bare mapping."""
    if isinstance(node, ast.Attribute) and node.attr == "status":
        return True
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == "status"
    )


def test_invitation_status_is_never_compared_to_a_bare_string():
    """The other half of the same rule: a status compared against a string literal lets a typo
    like ``"revokd"`` pass ``ty`` and ``make lint`` while reading a revoked invitation as valid.
    Compared against an ``InvitationStatus`` member instead, the same typo is an attribute ``ty``
    rejects — the type checker catching the violation before a test has to."""
    path = _APPS / "organizations" / "infra" / "invitation_router.py"
    offenders = {
        node.lineno
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Compare)
        and any(_status_access(side) for side in [node.left, *node.comparators])
        and any(
            isinstance(side, ast.Constant) and isinstance(side.value, str)
            for side in [node.left, *node.comparators]
        )
    }

    assert offenders == set()
