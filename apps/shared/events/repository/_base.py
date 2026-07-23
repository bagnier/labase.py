"""The base the concern mixins share — binds the model so they inherit its session and CRUD."""

from typing import ClassVar

from apps.shared.events.models import BusinessEventLog
from apps.shared.persistence.repository import BaseRepository


class _EventSQL(BaseRepository[BusinessEventLog]):
    model: ClassVar[type[BusinessEventLog]] = BusinessEventLog
