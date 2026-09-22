"""Contribs — the pull/collect contribution registry, split out of the event bus."""

from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.integration.contribs import Contribs


@dataclass(frozen=True)
class _Query:
    marker: str


@dataclass(frozen=True)
class _SessionQuery:
    session: AsyncSession


@pytest.mark.asyncio
async def test_collect_aggregates_every_provider_for_the_query_type():
    contribs = Contribs()

    async def one(q: _Query) -> str:
        return f"{q.marker}-1"

    async def two(q: _Query) -> str:
        return f"{q.marker}-2"

    contribs.provide(_Query, one)
    contribs.provide(_Query, two)

    assert await contribs.collect(_Query("x")) == ["x-1", "x-2"]


@pytest.mark.asyncio
async def test_collect_dispatches_by_exact_type_only():
    @dataclass(frozen=True)
    class _Sub(_Query):
        pass

    contribs = Contribs()

    async def base_provider(q: _Query) -> str:
        return "base"

    contribs.provide(_Query, base_provider)
    # A subclass query is a different key — the base provider must not answer it.
    assert await contribs.collect(_Sub("x")) == []


@pytest.mark.asyncio
async def test_collect_isolates_a_failing_provider_and_keeps_the_rest():
    contribs = Contribs()

    async def boom(q: _Query) -> str:
        raise RuntimeError(q.marker)

    async def ok(q: _Query) -> str:
        return "ok"

    contribs.provide(_Query, boom)
    contribs.provide(_Query, ok)

    # log-and-skip: the failure never propagates, the healthy provider still contributes.
    assert await contribs.collect(_Query("boom")) == ["ok"]


@pytest.mark.asyncio
async def test_collect_of_an_unknown_query_type_is_empty():
    assert await Contribs().collect(_Query("x")) == []


@pytest.mark.asyncio
async def test_collect_isolates_a_failing_sql_provider_so_the_session_stays_usable(
    db_session: AsyncSession,
):
    """A provider's SQL error aborts the caller's transaction: every later provider and the
    caller's own queries must still work — a down app can't break the page (README)."""
    contribs = Contribs()

    async def boom(q: _SessionQuery) -> None:
        await q.session.execute(text("select 1/0"))

    async def ok(q: _SessionQuery) -> int:
        result = await q.session.execute(text("select 2"))
        return result.scalar()

    contribs.provide(_SessionQuery, boom)
    contribs.provide(_SessionQuery, ok)

    result = await contribs.collect(_SessionQuery(db_session))
    assert result == [2]
    after = await db_session.execute(text("select 3"))
    assert after.scalar() == 3
