import uuid

from apps.shared.persistence.repository import PositionedRepository
from apps.todo.domain.models import TodoItem


class TodoRepository(PositionedRepository[TodoItem]):
    model = TodoItem
    default_order = TodoItem.position.asc()

    async def add(self, user_id: uuid.UUID, title: str) -> TodoItem:
        for item in await self.all():
            item.position += 1
        todo = TodoItem(user_id=user_id, org_id=self.org_id, title=title, position=0)
        return await self.save(todo)
