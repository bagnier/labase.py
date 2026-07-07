"""Browser-test teardown helpers — full table truncation and leftover data purge."""

import asyncio
import threading

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from apps.shared.config import get_technical_settings

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
        except Exception as e:  # noqa: BLE001 — re-raised on the calling thread below
            errors.append(e)
        finally:
            loop.close()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join()
    if errors:
        raise errors[0]
    return result[0]


def truncate_app_tables() -> None:
    """Truncates all application tables — used in browser test teardown."""

    s = get_technical_settings().supabase_database_schema
    tables = [
        "app_settings",
        "audit_logs",
        "error_events",
        "error_groups",
        "request_metrics",
        "org_file_share_tokens",
        "org_files",
        "todos",
        "card_states",
        "deck_subscriptions",
        "cards",
        "decks",
        "org_invitations",
        "memberships",
        "organizations",
        "profiles",
    ]
    truncate = "TRUNCATE TABLE " + ", ".join(f"{s}.{t}" for t in tables) + " CASCADE"

    async def _truncate() -> None:
        engine = _service_engine()
        try:
            # In-flight background writes (audit, metrics flush) can turn the
            # multi-table TRUNCATE into a deadlock victim — transient, retry.
            for attempt in range(3):
                try:
                    async with engine.begin() as conn:
                        await conn.execute(text(truncate))
                        # One-shot tasks (e.g. queued emails) must not leak across
                        # scenarios; recurring singletons stay — they are only
                        # replanted at app startup.
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


def reset_app_switches() -> None:
    """Clears persisted ``enabled`` overrides so feature switches don't leak across runs.

    Each app's ``mount()`` reads its ``enabled`` switch once, at process start (see
    apps.shared.settings) — there's no live unmount. So a leftover ``enabled = false`` in the
    shared dev/test DB would keep an app unmounted for the whole suite, until the next process
    start. Called from ``pytest_configure``, before any test module imports ``apps.main``.
    """

    async def _reset() -> None:
        engine = _service_engine()
        try:
            async with engine.begin() as conn:
                schema = get_technical_settings().supabase_database_schema
                await conn.execute(text(f"DELETE FROM {schema}.app_settings WHERE key = 'enabled'"))
        finally:
            await engine.dispose()

    _run_blocking(_reset)


async def purge_leftover_test_data() -> None:
    """Deletes test data that survives teardowns (from test email domains)."""
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
