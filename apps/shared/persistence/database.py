"""Async engines and session factories — the DB I/O substrate.

Two engines: user-role (RLS enforced) and BYPASSRLS admin, each pinned to the worktree's
schema via ``search_path`` and instrumented for the per-query SQL tally. Request sessions
commit before the response is sent; ``AdminSession`` is the BYPASSRLS session reserved for
event handlers, console queries and anonymous public surfaces (README: three DB sessions).
"""

from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from apps.shared.config import TechnicalSettings, get_technical_settings
from apps.shared.observability.sql import instrument_engine


def search_path_connect_args(settings: TechnicalSettings) -> dict:
    """asyncpg ``connect_args`` pinning every connection to the worktree's schema.

    One source of truth for the three engines that need it (user, admin, and the
    throwaway mount-time engine in ``settings_store``)."""
    return {"server_settings": {"search_path": f"{settings.supabase_database_schema},public"}}


def admin_url(settings: TechnicalSettings) -> str:
    """The BYPASSRLS admin DB URL, falling back to the user URL when unset."""
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
    """Close both pools while the loop still runs — the shutdown counterpart of the engines.

    Every background component stops on its own hook (task worker, tailer, flusher, drains); the
    pools were the one piece left to the interpreter's teardown, where closing an asyncpg
    connection has neither loop nor greenlet to await in. Only engines that were actually built
    are disposed: touching the lru_cache here would create one just to close it.
    """
    for build in (_user_engine, _admin_engine):
        if build.cache_info().currsize:
            await build().dispose()


@asynccontextmanager
async def _commit_on_success(session: AsyncSession):
    """Commit on clean exit, rollback on exception."""
    try:
        yield
        await session.commit()
    except Exception:
        await session.rollback()
        raise


async def _session(factory, request: Request | None = None) -> AsyncGenerator[AsyncSession]:
    # Transaction boundary: ideally commit before the response is sent.
    # FastAPI exposes fastapi_function_astack, whose teardown runs BEFORE
    # the response is sent (unlike fastapi_inner_astack, which runs after).
    # Without a request (e.g. direct tests), fallback: commit after yield.
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


# BYPASSRLS session — shared infra, owned by no context.
AdminSession = Annotated[AsyncSession, Depends(get_admin_session)]
