import uuid

from sqlalchemy import select

from apps.shared.persistence.repository import PositionedRepository
from apps.todo.domain.models import Todo


class TodoRepository(PositionedRepository[Todo]):
    model = Todo
    default_order = Todo.position.asc()

    async def add(self, user_id: uuid.UUID, title: str) -> Todo:
        for item in await self.all():
            item.position += 1
        todo = Todo(user_id=user_id, org_id=self.org_id, title=title, position=0)
        return await self.save(todo)

    async def recent_open(self, limit: int) -> list[Todo]:
        """This org's `limit` topmost open items — a bounded query, never `all()` filtered and
        sliced after the fact, so a large org's overview card costs `limit` rows, not every
        task it has, done included."""
        query = (
            select(Todo)
            .where(Todo.org_id == self.org_id, Todo.done.is_(False))
            .order_by(Todo.position)
            .limit(limit)
        )
        return list(await self.session.scalars(query))
