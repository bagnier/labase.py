"""Write path — append a fact (typed, or from explicit columns) and the single ``event → row``
mapping (no column dict between)."""

import uuid
from dataclasses import fields, is_dataclass
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.contextvars import get_contextvars

from apps.shared.events.models import BusinessEventLog
from apps.shared.events.repository._base import _EventSQL
from apps.shared.events.repository._delivery import LIFTED_COLUMNS
from apps.shared.events.types import BusinessEvent, OrgScoped, _is_secret_field_name
from apps.shared.persistence.database import admin_session_factory

log = structlog.get_logger("labase.business_events")


class _WritesEvents(_EventSQL):
    async def record(self, event: BusinessEvent) -> None:
        """Append a typed event to the trail on the bound session; the caller commits."""
        org_id = event.org_id if isinstance(event, OrgScoped) else None
        user_name, org_name = await self.pinned_names(event.user_id, org_id)
        await self.save(event_to_log(event, user_name=user_name, org_name=org_name))

    async def pinned_names(
        self, user_id: uuid.UUID | None, org_id: uuid.UUID | None
    ) -> tuple[str | None, str | None]:
        """Resolve the actor's handle and the org's name *now*, to store them on the row.

        One round trip for both: the write path already sat on a query for the handle, and a second
        one per emitted fact would double the cost of every business mutation. Both are read on the
        caller's session, so they see the same transaction the fact commits with.

        Profiles are ``own read`` under RLS, so a member cannot resolve a co-member's handle at read
        time; an org can be renamed or deleted outright. Pinning both here is what keeps the trail
        legible later."""
        if not user_id and not org_id:
            return None, None
        try:
            row = (
                await self.session.execute(
                    text(
                        "select (select handle from profiles where auth_user_id = :u),"
                        "       (select name from organizations where id = :o)"
                    ),
                    {"u": user_id, "o": org_id},
                )
            ).first()
        except Exception:
            return None, None
        return (row[0], row[1]) if row else (None, None)


def _loggable_payload(event: BusinessEvent) -> dict[str, Any]:
    if not is_dataclass(event) or isinstance(event, type):
        return {}
    payload: dict[str, Any] = {}
    for f in fields(event):
        value = getattr(event, f.name)
        if _is_secret_field_name(f.name):
            # Defence in depth: ``__init_subclass__`` already refuses a secret-named event field, so
            # reaching here means one slipped past (a raw or legacy writer). Mask it *and* shout — a
            # silent mask is how the leak stayed invisible; an error is what gets it fixed.
            if value is not None:
                log.error("business_event.secret_field_masked", field=f.name, kind=event.kind)
            payload[f.name] = "***" if value is not None else None
        elif isinstance(value, uuid.UUID):
            payload[f.name] = str(value)  # json-safe: stdlib json can't serialize a uuid.UUID
        elif isinstance(value, datetime):
            payload[f.name] = value.isoformat()  # json-safe; from_payload re-parses it back
        else:
            payload[f.name] = value
    return payload


def event_to_log(
    event: BusinessEvent, *, user_name: str | None = None, org_name: str | None = None
) -> BusinessEventLog:
    """The one ``event → row`` conversion. Scoping (user/org/entity) and the readable names are
    lifted to their own columns — so RLS, the timeline and full-text search reach them directly —
    leaving only the (redacted) rest in ``payload``; ``ip``/``request_id`` ride in from the request
    contextvars."""
    ctx = get_contextvars()
    request_id = ctx.get("request_id")
    payload = _loggable_payload(event)
    for lifted in LIFTED_COLUMNS:  # the lifted fields get their own columns, not a payload key
        payload.pop(lifted, None)
    # created_at is the trail's own column, filled by the model default (one clock) — never the
    # emitter's None, which would only shadow it. Drop it: the column is its one home.
    payload.pop("created_at", None)
    return BusinessEventLog(
        # The two halves the event declares; the row's ``kind`` is generated from them (a writer
        # cannot set it), so the trail composes its identity exactly as the class does.
        app_name=event.app_name,
        verb=event.verb,
        icon=event.icon,
        user_id=event.user_id,
        ip=ctx.get("ip"),
        # Scope is carried by the event's type, not by every event: only an OrgScoped fact names
        # an org. The column stays nullable — a server-wide fact legitimately has none.
        org_id=event.org_id if isinstance(event, OrgScoped) else None,
        entity_id=event.entity_id,  # the concerned entity's uuid pk, lifted to its own uuid column
        # The contextvar carries a str (structlog serializes it); the column is a uuid.
        request_id=uuid.UUID(request_id) if request_id else None,
        request_name=ctx.get("request_name"),
        payload=payload,
        user_name=user_name,
        entity_name=event.entity_name,
        org_name=org_name,
    )


async def insert_business_event(
    *,
    session: AsyncSession | None = None,
    app_name: str,
    verb: str,
    icon: str = "circle",  # the BusinessEvent base default — the trail always shows something
    user_id: uuid.UUID | None,
    ip: str | None,
    org_id: uuid.UUID | None,
    entity_id: uuid.UUID | None = None,
    entity_name: str | None = None,
    request_id: uuid.UUID | None,
    request_name: str | None = None,
    payload: dict[str, Any] | None,
) -> None:
    """Write a row from explicit columns — the seeding / non-event writer. With a ``session`` the
    row rides that transaction (atomic); without one, a best-effort admin write that swallows
    failures (seeders, tests). Only the write mixin is needed, so it binds ``_WritesEvents``
    directly rather than the fully composed repository."""

    async def write(s: AsyncSession) -> None:
        repo = _WritesEvents(s)
        stored = dict(payload) if payload else {}
        user_name, org_name = await repo.pinned_names(user_id, org_id)
        await repo.save(
            BusinessEventLog(
                app_name=app_name,
                verb=verb,
                icon=icon,
                user_id=user_id,
                ip=ip,
                org_id=org_id,
                entity_id=entity_id,
                request_id=request_id,
                request_name=request_name,
                payload=stored,
                user_name=user_name,
                entity_name=entity_name,
                org_name=org_name,
            )
        )

    if session is not None:
        await write(session)
        return
    try:
        async with admin_session_factory()() as own:
            await write(own)
            await own.commit()
    except Exception:
        log.warning("business_event.write_failed", kind=f"{app_name}.{verb}", user_id=user_id)
