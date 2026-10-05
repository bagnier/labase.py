"""The API roles hold only what migrations grant: Supabase's defaults (all privileges on every
new object) are revoked, so a forgotten grant stays closed. Read from ``public``, which PostgREST
serves.
"""

from collections.abc import AsyncIterator

import asyncpg
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from apps.shared.settings.env import get_technical_settings
from tests.rulebooks import BOOKS

_CRUD = ("SELECT", "INSERT", "UPDATE", "DELETE")

_MEMBER_TABLES = (
    "api_keys",
    "calendar_events",
    "card_states",
    "cards",
    "deck_subscriptions",
    "decks",
    "memberships",
    "org_files",
    "org_invitations",
    "page_nav_items",
    "pages",
    "profiles",
    "todos",
)

_TABLE_GRANTS = {
    *(("authenticated", table, p) for table in _MEMBER_TABLES for p in _CRUD),
    ("authenticated", "business_events", "SELECT"),
    ("app_rls", "consumed_events", "INSERT"),
    ("app_rls", "task_queue", "INSERT"),
    ("authenticated", "org_app_settings", "SELECT"),
    ("authenticated", "org_file_share_tokens", "INSERT"),
    ("authenticated", "org_file_share_tokens", "SELECT"),
    ("authenticated", "organizations", "SELECT"),
    # UPDATE is column-scoped; see test_authenticated_cannot_set_is_personal_through_postgrest.
}

_FUNCTION_GRANTS = {
    ("anon", "uuidv7"),
    ("authenticated", "accept_org_invitation"),
    ("authenticated", "create_org_with_owner"),
    ("app_rls", "api_key_principal"),
    ("app_rls", "get_invitation_by_token"),
    ("app_rls", "record_business_event"),
    ("app_rls", "second_factor_enrolled"),
    ("app_rls", "public_nav_items"),
    ("app_rls", "public_pages"),
    ("authenticated", "storage_path_org_id"),
    ("authenticated", "user_is_org_owner"),
    ("authenticated", "user_org_ids"),
    ("authenticated", "uuidv7"),
}

# The helpers a policy may call (AGENTS: the database enforces isolation and authorization).
_ISOLATION_HELPERS = {"storage_path_org_id", "user_org_ids"}
_AUTHORIZATION_HELPERS = {"user_is_org_owner"}

# Partitions included: a SQL session reaches them past the parent's RLS.
_TABLE_GRANTS_SQL = """
select r.rolname, c.relname, a.privilege_type
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
  cross join lateral aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
  join pg_roles r on r.oid = a.grantee
 where n.nspname = 'public'
   and c.relkind in ('r', 'p', 'v', 'm', 'f')
   and r.rolname in ('anon', 'authenticated', 'app_rls')
"""

# PUBLIC (grantee 0) is reported as such: it covers both API roles.
_FUNCTION_GRANTS_SQL = """
select coalesce(r.rolname, 'PUBLIC'), p.proname
  from pg_proc p
  join pg_namespace n on n.oid = p.pronamespace
  cross join lateral aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
  left join pg_roles r on r.oid = a.grantee
 where n.nspname = 'public'
   and (a.grantee = 0 or r.rolname in ('anon', 'authenticated', 'app_rls'))
"""

# A policy depends on the functions it calls; storage.objects included.
_POLICY_CALLS_SQL = """
select distinct p.proname
  from pg_policy pol
  join pg_depend d on d.classid = 'pg_policy'::regclass and d.objid = pol.oid
                  and d.refclassid = 'pg_proc'::regclass
  join pg_proc p on p.oid = d.refobjid
  join pg_namespace n on n.oid = p.pronamespace
 where n.nspname = 'public'
"""


_GUARDED_TABLES_SQL = """
select distinct c.relname
  from pg_policy pol
  join pg_class c on c.oid = pol.polrelid
  join pg_depend d on d.classid = 'pg_policy'::regclass and d.objid = pol.oid
                  and d.refclassid = 'pg_proc'::regclass
  join pg_proc p on p.oid = d.refobjid
  join pg_namespace n on n.oid = p.pronamespace
 where n.nspname = 'public' and p.proname = any(:helpers)
"""


@pytest_asyncio.fixture
async def admin_conn() -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(get_technical_settings().supabase_database_admin_url)
    try:
        async with engine.connect() as conn:
            yield conn
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_api_roles_hold_only_the_table_privileges_migrations_grant(
    admin_conn: AsyncConnection,
):
    rows = await admin_conn.execute(text(_TABLE_GRANTS_SQL))

    granted = {tuple(row) for row in rows}

    assert granted == _TABLE_GRANTS


@pytest.mark.asyncio
async def test_api_roles_execute_only_the_functions_migrations_grant(
    admin_conn: AsyncConnection,
):
    rows = await admin_conn.execute(text(_FUNCTION_GRANTS_SQL))

    granted = {tuple(row) for row in rows}

    assert granted == _FUNCTION_GRANTS


@pytest.mark.asyncio
async def test_authenticated_cannot_set_is_personal_through_postgrest(admin_conn: AsyncConnection):
    """Set once by ``create_org_with_owner``: flipped, it would dodge or break the personal-org
    guard."""
    rows = await admin_conn.execute(
        text(
            "select has_column_privilege('authenticated', 'public.organizations',"
            " 'is_personal', 'UPDATE')"
        )
    )

    can_update = rows.scalar_one()

    assert can_update is False


@pytest.mark.asyncio
async def test_the_secret_key_only_reads_the_journal(admin_conn: AsyncConnection):
    """Only ``record_business_event`` writes facts; the secret key cannot post or rewrite one."""
    rows = await admin_conn.execute(
        text(
            "select a.privilege_type from pg_class c"
            " cross join lateral aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a"
            " join pg_roles r on r.oid = a.grantee"
            " where c.oid = 'public.business_events'::regclass and r.rolname = 'service_role'"
        )
    )

    granted = set(rows.scalars())

    assert granted == {"SELECT"}


# The secret key's privileges: data only, not TRUNCATE or TRIGGER, with which a leaked key could
# wipe a table or plant a trigger on every tenant's writes.
_SERVICE_ROLE_TABLE_SQL = """
select c.relname, a.privilege_type
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
  cross join lateral aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
  join pg_roles r on r.oid = a.grantee
 where n.nspname = 'public'
   and c.relkind in ('r', 'p', 'v', 'm', 'f')
   and r.rolname = 'service_role'
"""


@pytest.mark.asyncio
async def test_the_secret_key_holds_data_privileges_only(admin_conn: AsyncConnection):
    relations = await admin_conn.execute(
        text(
            "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace"
            " where n.nspname = 'public' and c.relkind in ('r', 'p', 'v', 'm', 'f')"
        )
    )
    expected = {
        (relation, privilege)
        for relation in relations.scalars()
        for privilege in (("SELECT",) if relation == "business_events" else _CRUD)
    }

    rows = await admin_conn.execute(text(_SERVICE_ROLE_TABLE_SQL))

    assert {tuple(row) for row in rows} == expected


@pytest.mark.asyncio
async def test_a_table_created_later_gives_the_secret_key_data_privileges_only(
    admin_conn: AsyncConnection,
):
    """What a new table inherits: tomorrow's log partition, the next app's table."""
    rows = await admin_conn.execute(
        text(
            "select a.privilege_type from pg_default_acl d"
            " cross join lateral aclexplode(d.defaclacl) a"
            " join pg_roles r on r.oid = a.grantee"
            " where d.defaclrole = 'postgres'::regrole"
            " and d.defaclnamespace = 'public'::regnamespace and d.defaclobjtype = 'r'"
            " and r.rolname = 'service_role'"
        )
    )

    assert set(rows.scalars()) == set(_CRUD)


@pytest.mark.asyncio
async def test_every_public_table_enforces_row_level_security(admin_conn: AsyncConnection):
    rows = await admin_conn.execute(
        text(
            "select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace"
            " where n.nspname = 'public' and c.relkind in ('r', 'p') and not c.relispartition"
            " and not c.relrowsecurity"
        )
    )

    unprotected = set(rows.scalars())

    assert unprotected == set()


@pytest.mark.asyncio
async def test_every_security_definer_function_pins_its_search_path(admin_conn: AsyncConnection):
    # Unpinned, a name resolves on the caller's search_path with the owner's rights.
    rows = await admin_conn.execute(
        text(
            "select p.proname from pg_proc p join pg_namespace n on n.oid = p.pronamespace"
            " where n.nspname = 'public' and p.prosecdef"
            " and not coalesce(p.proconfig, '{}') @> array['search_path=\"\"']"
        )
    )

    unpinned = set(rows.scalars())

    assert unpinned == set()


@pytest.mark.asyncio
async def test_every_function_a_policy_calls_is_a_declared_guard(admin_conn: AsyncConnection):
    rows = await admin_conn.execute(text(_POLICY_CALLS_SQL))

    called = set(rows.scalars())

    assert called == _ISOLATION_HELPERS | _AUTHORIZATION_HELPERS


@pytest.mark.asyncio
async def test_every_table_an_authorization_helper_guards_has_its_rules(
    admin_conn: AsyncConnection,
):
    """Each table with authorization policies has at least one rule."""
    rows = await admin_conn.execute(
        text(_GUARDED_TABLES_SQL), {"helpers": sorted(_AUTHORIZATION_HELPERS)}
    )

    unruled = set(rows.scalars()) - {rule.table for book in BOOKS for rule in book.rules}

    assert unruled == set()


@pytest.mark.asyncio
async def test_the_app_user_role_opens_with_no_password_known_in_advance():
    admin_url = make_url(get_technical_settings().supabase_database_admin_url)
    dsn = admin_url.set(
        drivername="postgresql", username="app_user", password="app_user_password"
    ).render_as_string(hide_password=False)

    with pytest.raises(asyncpg.InvalidAuthorizationSpecificationError):
        await asyncpg.connect(dsn)


def _as_anon(method: str, path: str, **kwargs) -> int:
    settings = get_technical_settings()
    response = httpx.request(
        method,
        f"{settings.supabase_api_url}/rest/v1/{path}",
        headers={"apikey": settings.supabase_publishable_key},
        **kwargs,
    )
    return response.status_code


def test_the_publishable_key_reads_public_pages():
    status = _as_anon("GET", "pages", params={"select": "slug"})

    assert status == httpx.codes.OK


def test_the_publishable_key_cannot_read_which_org_a_page_belongs_to():
    status = _as_anon("GET", "pages", params={"select": "org_id"})

    assert status == httpx.codes.UNAUTHORIZED


def test_the_publishable_key_cannot_list_share_tokens():
    status = _as_anon("GET", "org_file_share_tokens", params={"select": "token"})

    assert status == httpx.codes.UNAUTHORIZED


def test_the_publishable_key_cannot_roll_log_partitions():
    # A window dropping nothing, should the call pass.
    status = _as_anon(
        "POST", "rpc/roll_log_partitions", json={"p_today": "2026-01-01", "p_retention_days": 36500}
    )

    assert status == httpx.codes.UNAUTHORIZED
