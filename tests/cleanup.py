"""Browser-test teardown helpers — full table truncation and leftover data purge."""

import asyncio
import threading

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.shared.config import get_settings

_TEST_EMAIL_DOMAINS = ["test.local", "example.com", "rls.local"]


def _service_engine():
    settings = get_settings()
    url = settings.database_url_service or settings.database_url
    connect_args = {"server_settings": {"search_path": f"{settings.db_schema},public"}}
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

    async def _truncate() -> None:
        engine = _service_engine()
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "TRUNCATE TABLE public.audit_logs, public.org_file_share_tokens, "
                        "public.org_files, public.todos, "
                        "public.card_states, public.deck_subscriptions, public.cards, "
                        "public.decks, public.org_invitations, "
                        "public.memberships, public.organizations, public.profiles CASCADE"
                    )
                )
                await conn.execute(
                    text("DELETE FROM auth.users WHERE split_part(email, '@', 2) = ANY(:domains)"),
                    {"domains": _TEST_EMAIL_DOMAINS},
                )
        finally:
            await engine.dispose()

    _run_blocking(_truncate)


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
