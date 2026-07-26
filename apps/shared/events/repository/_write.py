"""Write path — append a fact, and the single ``event → row`` mapping (no column dict between)."""

import uuid
from dataclasses import fields, is_dataclass
from typing import Any

from sqlalchemy import text
from structlog.contextvars import get_contextvars

from apps.shared.events.models import BusinessEventLog
from apps.shared.events.repository._base import _EventSQL
from apps.shared.events.types import BusinessEvent


class _WritesEvents(_EventSQL):
    async def record(self, event: BusinessEvent) -> None:
        """Append a typed event to the trail on the bound session; the caller commits."""
        actor_name = await self.user_handle(event.user_id)
        await self.save(event_to_log(event, actor_name=actor_name))

    async def user_handle(self, user_id: uuid.UUID | None) -> str | None:
        """Resolve a user's handle for denormalization (the actor, or a user subject). Profiles are
        ``own read`` under RLS, so a member can't resolve another user's handle at read time — this
        pins it as it was then."""
        if not user_id:
            return None
        try:
            return await self.session.scalar(
                text("select handle from profiles where auth_user_id = :id"),
                {"id": user_id},  # already a uuid — the column compare holds
            )
        except Exception:
            return None


# Field-name substrings whose value is masked before it reaches the payload (``access_token`` etc.).
_REDACT_SUBSTRINGS = ("token", "password", "secret")


def _loggable_payload(event: BusinessEvent) -> dict[str, Any]:
    if not is_dataclass(event) or isinstance(event, type):
        return {}
    payload: dict[str, Any] = {}
    for f in fields(event):
        value = getattr(event, f.name)
        if any(s in f.name.lower() for s in _REDACT_SUBSTRINGS):
            payload[f.name] = "***" if value is not None else None
        elif isinstance(value, uuid.UUID):
            payload[f.name] = str(value)  # json-safe: stdlib json can't serialize a uuid.UUID
        else:
            payload[f.name] = value
    return payload


def event_to_log(event: BusinessEvent, *, actor_name: str | None = None) -> BusinessEventLog:
    """The one ``event → row`` conversion. Scoping (user/org/entity) is lifted to its own columns —
    so RLS and the timeline can filter on them — leaving only the (redacted) rest in ``payload``;
    ``ip``/``request_id`` ride in from the request contextvars."""
    ctx = get_contextvars()
    payload = _loggable_payload(event)
    payload.pop("user_id", None)
    payload.pop("org_id", None)
    payload.pop("entity_id", None)
    if actor_name:
        payload["actor_name"] = actor_name
    if not payload.get("entity_name"):  # a base field on every event — drop it when unset
        payload.pop("entity_name", None)
    return BusinessEventLog(
        kind=event.kind,
        level=event.level,
        icon=event.icon,
        user_id=event.user_id,
        ip=ctx.get("ip"),
        org_id=event.org_id,
        entity_id=event.entity_id,  # the concerned entity's uuid pk, lifted to its own uuid column
        request_id=ctx.get("request_id"),
        payload=payload or None,
    )
