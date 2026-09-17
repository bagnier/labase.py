"""The API roles hold exactly the privileges a migration grants them — nothing inherited.

Supabase's default privileges hand ``anon`` and ``authenticated`` every table privilege and
EXECUTE on every new object in ``public``; the foundation migration revokes that, so a table or
function a migration forgets to grant stays closed instead of wide open to the publishable key.
These tests read the catalog of the stack's ``public`` schema — the one PostgREST serves.
"""

from collections.abc import AsyncIterator

import asyncpg
import httpx
import pytest
import pytest_asyncio
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from apps.shared.settings.env import get_technical_settings

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
    "organizations",
    "page_nav_items",
    "pages",
    "profiles",
    "todos",
)

_TABLE_GRANTS = {
    ("anon", "pages", "SELECT"),
    *(("authenticated", table, p) for table in _MEMBER_TABLES for p in _CRUD),
    ("authenticated", "business_events", "SELECT"),
    ("authenticated", "consumed_events", "INSERT"),
    ("authenticated", "org_app_settings", "SELECT"),
    ("authenticated", "org_file_share_tokens", "INSERT"),
    ("authenticated", "org_file_share_tokens", "SELECT"),
    ("authenticated", "task_queue", "INSERT"),
    ("authenticated", "todo_completion_stats", "SELECT"),
}

_FUNCTION_GRANTS = {
    ("anon", "uuidv7"),
    ("authenticated", "accept_org_invitation"),
    ("authenticated", "record_business_event"),
    ("authenticated", "user_is_org_owner"),
    ("authenticated", "user_org_ids"),
    ("authenticated", "uuidv7"),
}

# Every relation, partitions included: PostgREST does not serve a partition, but a SQL session on
# an API role reaches it directly, where the parent's RLS does not apply.
_TABLE_GRANTS_SQL = """
select r.rolname, c.relname, a.privilege_type
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
  cross join lateral aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
  join pg_roles r on r.oid = a.grantee
 where n.nspname = 'public'
   and c.relkind in ('r', 'p', 'v', 'm', 'f')
   and r.rolname in ('anon', 'authenticated')
"""

# PUBLIC (grantee 0) is reported as such: it covers both API roles.
_FUNCTION_GRANTS_SQL = """
select coalesce(r.rolname, 'PUBLIC'), p.proname
  from pg_proc p
  join pg_namespace n on n.oid = p.pronamespace
  cross join lateral aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
  left join pg_roles r on r.oid = a.grantee
 where n.nspname = 'public'
   and (a.grantee = 0 or r.rolname in ('anon', 'authenticated'))
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
    # Unpinned, an unqualified name resolves on the caller's search_path, with the owner's rights.
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


def test_the_publishable_key_cannot_list_share_tokens():
    status = _as_anon("GET", "org_file_share_tokens", params={"select": "token"})

    assert status == httpx.codes.UNAUTHORIZED


def test_the_publishable_key_cannot_roll_log_partitions():
    # A window long enough to drop nothing, should the call get through.
    status = _as_anon(
        "POST", "rpc/roll_log_partitions", json={"p_today": "2026-01-01", "p_retention_days": 36500}
    )

    assert status == httpx.codes.UNAUTHORIZED
