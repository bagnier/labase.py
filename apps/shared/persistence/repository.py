"""The repository bases every context inherits, and the counting helpers its cards ask for.

A repository is where one table's queries live — the house rule being that no SQL against that
table exists anywhere else. These bases hold what all of them would otherwise repeat: the CRUD,
the org filter, and the ordering of a hand-sortable list.

:class:`OrgScopedRepository` filters on ``org_id`` for ergonomics, never for safety. RLS decides
who sees what; a Python filter that looked like the boundary would invite the next reader to trust
it, and it would hold right up until someone wrote a query without it.
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
    """Every query filtered by ``org_id`` — ergonomic scoping, not the isolation boundary.
    RLS remains the single source of truth for who sees what (README)."""

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


class PositionedRepository[T: Base](OrgScopedRepository[T]):
    """Org-scoped rows kept in a dense, 0-based `position` order.

    `move_above` re-derives every position by load-then-mutate-then-flush so the
    optimistic lock (`version_id_col`) engages — never bulk `update()`, which
    would bypass it. `position_key` names the attribute callers identify rows
    by: the primary key by default, `page_id` for pages' nav items.
    """

    position_key: ClassVar[str] = "id"

    @classmethod
    def _reorder(cls, items: list[T], item_key: Any, above_key: Any | None) -> list[T] | None:
        """Pure reordering: `items` (position order) with `item_key` moved above
        `above_key`, or to the end when `above_key` is None. None if either key
        is unknown (concurrent deletion) — callers treat that as a no-op."""
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
    """How many `model` rows match `criteria` — all of them when none is given.

    The one place `count(*)`'s result is coalesced. An aggregate always returns exactly one row,
    so `scalar()`'s `int | None` is SQLAlchemy's stub not knowing that, never a real absence:
    the `or 0` is the adapter for that imprecision and belongs here alone, not at each call site.
    """
    return int(await session.scalar(select(func.count()).select_from(model).where(*criteria)) or 0)


async def count_all(session: AsyncSession, model: type[Any]) -> int:
    """Server-wide count for `model`, across every organisation (console overview)."""
    return await count_where(session, model)


async def count_created_per_day(
    session: AsyncSession, model: type[Any], *, days: int
) -> dict[str, int]:
    """Server-wide rows per creation day over the trailing window, as ``{iso_day: n}`` —
    the ``growth`` slice a console tile may carry for the landing growth chart."""
    since = clock.now() - timedelta(days=days - 1)
    day = func.date(model.created_at)
    rows = await session.execute(
        select(day, func.count()).where(model.created_at >= since).group_by(day)
    )
    return {d.isoformat(): int(n) for d, n in rows.all()}
