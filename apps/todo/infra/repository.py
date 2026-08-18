import uuid

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
