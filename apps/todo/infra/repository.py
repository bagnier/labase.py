import uuid

from sqlalchemy import select

from apps.shared.persistence.repository import PositionedRepository
from apps.todo.domain.models import Todo, TodoCompletionStats


class TodoRepository(PositionedRepository[Todo]):
    model = Todo
    default_order = Todo.position.asc()

    async def add(self, user_id: uuid.UUID, title: str) -> Todo:
        for item in await self.all():
            item.position += 1
        todo = Todo(user_id=user_id, org_id=self.org_id, title=title, position=0)
        return await self.save(todo)

    async def completion_count(self) -> int:
        """The org's completions ever — 0 before its first tick (no row yet)."""
        tally = await self.session.scalar(
            select(TodoCompletionStats.completed_count).where(
                TodoCompletionStats.org_id == self.org_id
            )
        )
        return tally or 0
