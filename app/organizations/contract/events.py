"""Org's public event — emitted post-commit once a new organisation and its owner exist.

Org owns and emits this; apps subscribe (welcome seeding) without importing one another.
The carrying mechanism is the :class:`~app.integration.EventBus`. ``OrgCreated``
subscribers run as background tasks, so the org is guaranteed to exist when they execute.
"""

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class OrgCreated:
    org_id: uuid.UUID
    access_token: str
