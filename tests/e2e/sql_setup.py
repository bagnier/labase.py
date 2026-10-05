"""Committed SQL setup in the app's schema (``test``, or ``wt_<name>_test`` in a worktree),
through SQLAlchemy: PostgREST is pinned to ``public``. Committed, so Storage RLS sees it.
"""

import asyncio
import threading
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from apps.shared.settings.env import get_technical_settings


def _engine():
    s = get_technical_settings()
    url = s.supabase_database_admin_url or s.supabase_database_user_url
    connect_args = {"server_settings": {"search_path": f"{s.supabase_database_schema},public"}}
    return create_async_engine(url, poolclass=NullPool, connect_args=connect_args)


def run_sql(
    sql: str,
    params: Mapping[str, Any] | None = None,
    *,
    fetch: bool = False,
    bypass_triggers: bool = False,
):
    """Run and commit a statement, rows returned as dicts. ``bypass_triggers`` silences triggers,
    to force states the app forbids (a sole owner demoted)."""

    async def _exec() -> list[dict]:
        engine = _engine()
        try:
            async with engine.begin() as conn:
                if bypass_triggers:
                    await conn.execute(text("set local session_replication_role = replica"))
                result = await conn.execute(text(sql), params or {})
                return [dict(r) for r in result.mappings().all()] if fetch else []
        finally:
            await engine.dispose()

    out: list = []
    errors: list[Exception] = []

    def _target() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            out.append(loop.run_until_complete(_exec()))
        except Exception as e:
            errors.append(e)
        finally:
            loop.close()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join()
    if errors:
        raise errors[0]
    return out[0]
