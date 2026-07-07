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

from apps.shared.config import get_technical_settings
from apps.shared.observability.sql import instrument_engine


@lru_cache
def _user_engine():
    settings = get_technical_settings()
    connect_args = {
        "server_settings": {"search_path": f"{settings.supabase_database_schema},public"}
    }
    engine = create_async_engine(
        settings.supabase_database_user_url,
        echo=False,
        pool_pre_ping=True,
        connect_args=connect_args,
    )
    instrument_engine(engine)
    return engine


@lru_cache
def _admin_engine():
    settings = get_technical_settings()
    url = settings.supabase_database_admin_url or settings.supabase_database_user_url
    connect_args = {
        "server_settings": {"search_path": f"{settings.supabase_database_schema},public"}
    }
    engine = create_async_engine(url, echo=False, pool_pre_ping=True, connect_args=connect_args)
    instrument_engine(engine)
    return engine


def _make_session_factory(engine_fn):
    @lru_cache
    def factory():
        return async_sessionmaker(engine_fn(), class_=AsyncSession, expire_on_commit=False)

    return factory


_user_session_factory = _make_session_factory(_user_engine)
admin_session_factory = _make_session_factory(_admin_engine)


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
