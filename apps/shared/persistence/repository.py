"""Repository bases (one table's queries live in its repository, nowhere else) and the counting
helpers overview cards use.

:class:`OrgScopedRepository` filters on ``org_id`` for convenience, not safety: RLS isolates
(AGENTS: the database enforces isolation and authorization).
"""

import uuid
from datetime import timedelta
from operator import attrgetter
from typing import Any, ClassVar, cast

from sqlalchemy import ColumnExpressionArgument, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared import clock
from apps.shared.persistence.base import Base, Positioned


class BaseRepository[T: Base]:
    model: ClassVar[type[Any]]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, pk: uuid.UUID) -> T | None:
        return cast(T | None, await self.session.get(self.model, pk))

    async def all(self) -> list[T]:
        return cast(list[T], list(await self.session.scalars(select(self.model))))

    async def save(self, entity: T) -> T:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def delete(self, entity: T) -> None:
        await self.session.delete(entity)
        await self.session.flush()

    async def count(self) -> int:
        return await count_where(self.session, self.model)


class OrgScopedRepository[T: Base](BaseRepository[T]):
    """Every query filtered by ``org_id``; see the module docstring."""

    default_order: ClassVar[Any | None] = None

    def __init__(self, session: AsyncSession, org_id: uuid.UUID) -> None:
        super().__init__(session)
        self.org_id = org_id

    async def get(self, pk: uuid.UUID) -> T | None:
        return cast(
            T | None,
            await self.session.scalar(
                select(self.model).where(
                    self.model.id == pk,
                    self.model.org_id == self.org_id,
                )
            ),
        )

    async def all(self) -> list[T]:
        query = select(self.model).where(self.model.org_id == self.org_id)
        if self.default_order is not None:
            query = query.order_by(self.default_order)
        return cast(list[T], list(await self.session.scalars(query)))

    async def count(self) -> int:
        return await count_where(self.session, self.model, self.model.org_id == self.org_id)

    async def recent(self, limit: int) -> list[T]:
        """The first `limit` rows in `default_order`, then newest `id`: rows sharing a
        timestamp (one request, a pinned test clock) would otherwise come in any order."""
        order = [self.default_order] if self.default_order is not None else []
        query = (
            select(self.model)
            .where(self.model.org_id == self.org_id)
            .order_by(*order, self.model.id.desc())
            .limit(limit)
        )
        return cast(list[T], list(await self.session.scalars(query)))


class PositionedRepository[T: Base](OrgScopedRepository[T]):
    """Org-scoped rows in a dense, 0-based `position` order.

    Positions are rewritten row by row, never with a bulk `update()`, which would bypass the
    optimistic lock. `position_key` is how callers name a row: `id`, or `page_id` for nav items.
    """

    position_key: ClassVar[str] = "id"

    @classmethod
    def _reorder(cls, items: list[T], item_key: Any, above_key: Any | None) -> list[T] | None:
        """`items` with `item_key` moved above `above_key`, or last when it is None. None if
        either key is gone (a concurrent deletion): a no-op."""
        key = attrgetter(cls.position_key)
        item = next((i for i in items if key(i) == item_key), None)
        if item is None:
            return None
        ordered = [i for i in items if key(i) != item_key]
        if above_key is None:
            ordered.append(item)
        else:
            above_idx = next(
                (i for i, entry in enumerate(ordered) if key(entry) == above_key), None
            )
            if above_idx is None:
                return None
            ordered.insert(above_idx, item)
        return ordered

    async def move_above(self, item_key: Any, above_key: Any | None) -> None:
        ordered = self._reorder(await self.all(), item_key, above_key)
        if ordered is None:
            return
        for pos, entry in enumerate(ordered):
            cast(Positioned, entry).position = pos
        await self.session.flush()


async def count_where(
    session: AsyncSession, model: type[Any], *criteria: ColumnExpressionArgument[bool]
) -> int:
    """Rows of `model` matching `criteria`. The `or 0` only satisfies SQLAlchemy's `int | None`
    stub: `count(*)` always returns a row."""
    return int(await session.scalar(select(func.count()).select_from(model).where(*criteria)) or 0)


async def count_all(session: AsyncSession, model: type[Any]) -> int:
    """Across every organization, for the console."""
    return await count_where(session, model)


async def count_created_per_day(
    session: AsyncSession, model: type[Any], *, days: int
) -> dict[str, int]:
    """``{iso_day: n}`` created across the server over the last ``days``, for console growth
    charts."""
    since = clock.now() - timedelta(days=days - 1)
    day = func.date(model.created_at)
    rows = await session.execute(
        select(day, func.count()).where(model.created_at >= since).group_by(day)
    )
    return {d.isoformat(): int(n) for d, n in rows.all()}
