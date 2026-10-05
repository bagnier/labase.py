"""Browser-test teardown: truncation and leftover data purge."""

import asyncio
import threading

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from apps.shared.settings.env import get_technical_settings
from apps.shared.settings.store import BOOL_FALSE, AppSetting

_TEST_EMAIL_DOMAINS = ["test.local", "example.com", "rls.local"]


def _service_engine():
    settings = get_technical_settings()
    url = settings.supabase_database_admin_url or settings.supabase_database_user_url
    connect_args = {
        "server_settings": {"search_path": f"{settings.supabase_database_schema},public"}
    }
    return create_async_engine(url, poolclass=NullPool, connect_args=connect_args)


def _run_blocking(coro_factory):
    result: list = []
    errors: list[Exception] = []

    def _target() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result.append(loop.run_until_complete(coro_factory()))
        except Exception as e:
            errors.append(e)
        finally:
            loop.close()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join()
    if errors:
        raise errors[0]
    return result[0]


# Emptied by a DELETE below that spares the recurring rows: nothing would replant them.
_KEEP_TABLES = ["task_queue"]

_TABLES_QUERY = """
select c.relname
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = :schema
   and c.relkind in ('r', 'p')  -- ordinary and partitioned tables — never a partition child
   and not c.relispartition
"""


def truncate_app_tables() -> None:
    """Truncate every table of the schema, read from the catalog: ``CASCADE`` misses a new
    table nothing references."""

    s = get_technical_settings().supabase_database_schema

    async def _truncate() -> None:
        engine = _service_engine()
        try:
            # A background write can make the TRUNCATE a deadlock victim: retry.
            for attempt in range(3):
                try:
                    async with engine.begin() as conn:
                        rows = await conn.execute(text(_TABLES_QUERY), {"schema": s})
                        tables = [r.relname for r in rows if r.relname not in _KEEP_TABLES]
                        truncate = (
                            "TRUNCATE TABLE " + ", ".join(f"{s}.{t}" for t in tables) + " CASCADE"
                        )
                        await conn.execute(text(truncate))
                        # Recurring rows stay: only startup replants them.
                        await conn.execute(
                            text(f"DELETE FROM {s}.task_queue WHERE recurring_seconds IS NULL")
                        )
                        await conn.execute(
                            text(
                                "DELETE FROM auth.users "
                                "WHERE split_part(email, '@', 2) = ANY(:domains)"
                            ),
                            {"domains": _TEST_EMAIL_DOMAINS},
                        )
                    return
                except DBAPIError:
                    if attempt == 2:
                        raise
                    await asyncio.sleep(0.5)
        finally:
            await engine.dispose()

    _run_blocking(_truncate)


def truncate_tables(names: list[str]) -> None:
    """Truncate ``tables``, for rows committed outside the API driver's transaction."""
    s = get_technical_settings().supabase_database_schema
    stmt = "TRUNCATE TABLE " + ", ".join(f"{s}.{t}" for t in names) + " CASCADE"

    async def _do() -> None:
        engine = _service_engine()
        try:
            async with engine.begin() as conn:
                await conn.execute(text(stmt))
        finally:
            await engine.dispose()

    _run_blocking(_do)


def reset_app_switches() -> None:
    """Delete stored ``enabled`` switches before ``apps.main`` is imported: mount reads them once,
    and a leftover ``false`` would unmount an app for the whole run."""

    async def _reset() -> None:
        engine = _service_engine()
        try:
            async with engine.begin() as conn:
                schema = get_technical_settings().supabase_database_schema
                await conn.execute(text(f"DELETE FROM {schema}.app_settings WHERE key = 'enabled'"))
        finally:
            await engine.dispose()

    _run_blocking(_reset)


_SEEDING_KEY = "seed_welcome_content"


def disable_welcome_seeding() -> None:
    """Turn welcome seeding off for the run, as an admin would, before ``apps.main`` is imported:
    starter rows would skew every count. Seeding scenarios turn it back on."""

    async def _disable() -> None:
        engine = _service_engine()
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    insert(AppSetting)
                    .values(app_name="organizations", key=_SEEDING_KEY, value=BOOL_FALSE)
                    .on_conflict_do_update(
                        index_elements=["app_name", "key"], set_={"value": BOOL_FALSE}
                    )
                )
        finally:
            await engine.dispose()

    _run_blocking(_disable)


async def purge_leftover_test_data() -> None:
    """Delete what survives teardowns (test email domains)."""
    engine = _service_engine()
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM auth.users WHERE split_part(email, '@', 2) = ANY(:domains)"),
                {"domains": _TEST_EMAIL_DOMAINS},
            )
            await conn.execute(
                text("""
                    DELETE FROM organizations o
                    WHERE NOT EXISTS (SELECT 1 FROM memberships m WHERE m.org_id = o.id)
                """)
            )
    finally:
        await engine.dispose()
