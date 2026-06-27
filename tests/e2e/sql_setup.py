"""Synchronous SQL helpers for test setup, run against the *active* DB schema.

Test ``given`` helpers must write to the same schema the app reads (``DB_SCHEMA`` —
``test`` for the main repo, ``wt_<name>_test`` for a worktree). PostgREST is pinned to
``public`` and cannot target those schemas, so setup goes through SQLAlchemy instead,
whose engine sets ``search_path = <schema>,public``. Writes are committed (outside any
test transaction) so Supabase Storage RLS — which reads the committed DB — can see them.
"""

import asyncio
import threading
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from apps.shared.config import get_technical_settings


def _engine():
    s = get_technical_settings()
    url = s.database_url_service or s.database_url
    connect_args = {"server_settings": {"search_path": f"{s.db_schema},public"}}
    return create_async_engine(url, poolclass=NullPool, connect_args=connect_args)


def run_sql(sql: str, params: Mapping[str, Any] | None = None, *, fetch: bool = False):
    """Execute a committed statement against the active schema; optionally return rows as dicts."""

    async def _exec() -> list[dict]:
        engine = _engine()
        try:
            async with engine.begin() as conn:
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
        except Exception as e:  # noqa: BLE001 — re-raised on the calling thread below
            errors.append(e)
        finally:
            loop.close()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join()
    if errors:
        raise errors[0]
    return out[0]
