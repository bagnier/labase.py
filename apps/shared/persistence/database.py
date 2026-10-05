"""Engines and session dependencies (AGENTS: three sessions, and RLS by default).

Two engines, user role and BYPASSRLS admin, both pinned to the worktree's schema and instrumented
for the per-request SQL tally.
"""

from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.shared.persistence.sql_stats import instrument_engine
from apps.shared.settings.env import TechnicalSettings, get_technical_settings


def search_path_connect_args(settings: TechnicalSettings) -> dict:
    """Pins a connection to the worktree's schema; also used by ``settings.store``'s engine."""
    return {"server_settings": {"search_path": f"{settings.supabase_database_schema},public"}}


def admin_url(settings: TechnicalSettings) -> str:
    """Falls back to the user URL when unset."""
    return settings.supabase_database_admin_url or settings.supabase_database_user_url


@lru_cache
def _user_engine():
    settings = get_technical_settings()
    engine = create_async_engine(
        settings.supabase_database_user_url,
        echo=False,
        pool_pre_ping=True,
        connect_args=search_path_connect_args(settings),
    )
    instrument_engine(engine)
    return engine


@lru_cache
def _admin_engine():
    settings = get_technical_settings()
    engine = create_async_engine(
        admin_url(settings),
        echo=False,
        pool_pre_ping=True,
        connect_args=search_path_connect_args(settings),
    )
    instrument_engine(engine)
    return engine


def _make_session_factory(engine_fn):
    @lru_cache
    def factory():
        return async_sessionmaker(engine_fn(), class_=AsyncSession, expire_on_commit=False)

    return factory


_user_session_factory = _make_session_factory(_user_engine)
admin_session_factory = _make_session_factory(_admin_engine)


async def dispose_engines() -> None:
    """Close the pools at shutdown, while a loop remains to close asyncpg connections on. Only
    engines already built: calling the cached builder would create one to close it."""
    for build in (_user_engine, _admin_engine):
        if build.cache_info().currsize:
            await build().dispose()


@asynccontextmanager
async def _commit_on_success(session: AsyncSession):
    try:
        yield
        await session.commit()
    except Exception:
        await session.rollback()
        raise


async def _session(factory, request: Request | None = None) -> AsyncGenerator[AsyncSession]:
    # Commit before the response is sent: ``fastapi_function_astack`` unwinds before it,
    # ``fastapi_inner_astack`` after. Without a request (direct tests), commit after the yield.
    async with factory()() as session:
        func_stack: AsyncExitStack | None = (
            request.scope.get("fastapi_function_astack") if request is not None else None
        )
        if func_stack is not None:
            await func_stack.enter_async_context(_commit_on_success(session))
            yield session
        else:
            yield session
            await session.commit()


async def get_user_session(request: Request) -> AsyncGenerator[AsyncSession]:
    async for session in _session(_user_session_factory, request):
        yield session


async def get_admin_session(request: Request) -> AsyncGenerator[AsyncSession]:
    async for session in _session(admin_session_factory, request):
        yield session


AdminSession = Annotated[AsyncSession, Depends(get_admin_session)]
