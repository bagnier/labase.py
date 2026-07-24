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
        handle = await self.actor_handle(event.actor_id)
        await self.save(event_to_log(event, actor=handle))

    async def actor_handle(self, user_id: uuid.UUID | None) -> str | None:
        """Denormalize *who* at write time: profiles are ``own read`` under RLS, so a member can't
        resolve a co-member's handle at read time — and this pins the handle as it was then."""
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


def event_to_log(event: BusinessEvent, *, actor: str | None = None) -> BusinessEventLog:
    """The one ``event → row`` conversion. Scoping (actor/org/entity) is lifted to its own columns —
    so RLS and the timeline can filter on them — leaving only the (redacted) rest in ``payload``;
    ``ip``/``request_id`` ride in from the request contextvars."""
    ctx = get_contextvars()
    payload = _loggable_payload(event)
    payload.pop("actor_id", None)
    payload.pop("org_id", None)
    payload.pop("entity_id", None)
    if actor:
        payload["actor"] = actor
    return BusinessEventLog(
        kind=event.kind,
        level=event.level,
        icon=event.icon,
        user_id=event.actor_id,
        ip=ctx.get("ip"),
        org_id=event.org_id,
        # entity_id is polymorphic (uuid pk / slug / int) and lands in a text column — the one place
        # a uuid concerned-entity id is stringified, so emit sites pass it raw.
        entity_id=str(event.entity_id) if event.entity_id is not None else None,
        request_id=ctx.get("request_id"),
        payload=payload or None,
    )
