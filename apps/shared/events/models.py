"""The shape of a business event on the trail.

One data structure, no behaviour: :class:`BusinessEventRecord` is the ORM mapping of the append-only
``business_events`` table — the single shape written on ``emit`` *and* handed back on a read (the
session keeps ``expire_on_commit=False``, so a read row stays usable past its session). Access logic
— writing and querying it — lives in the repository; humanizing a row for a surface lives in
:mod:`apps.shared.events.timeline`.

This model maps only the columns that *are the fact* — the ones a reader projects and a consumer
rebuilds. The delivery-plumbing column ``dispatched_at`` (the async tailer's claim cursor) is
deliberately **not** mapped here: it is queue mechanics, not part of what happened, and the listener
touches it through raw SQL in :mod:`apps.shared.events.repository._delivery` (alongside the
``consumed`` ledger). Keeping it off the model is what lets this class stay "the fact, and only the
fact"; the choice lives here so the absence reads as intent, not oversight.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Computed, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared import clock
from apps.shared.persistence.base import Base, UUIDPk


class BusinessEventRecord(Base, UUIDPk):
    """The append-only business-event row. Members read their own / their orgs' rows via RLS.

    One writer: the ``record_business_event`` SECURITY DEFINER function (C4). ``emit`` calls it on
    the session the caller names, so the fact commits atomically with the mutation; the function
    inserts as its owner, so no raw table INSERT grant is exposed — a member (or a PostgREST client
    on the same role) can no longer POST the trail table directly. That session is usually the
    caller's own RLS (``authenticated``) one; the auth routes pass the **BYPASSRLS admin** session
    instead, since a caller signing in or out has no RLS identity to write under. The signup trigger
    is the one exception: it inserts directly, itself SECURITY DEFINER, because user creation
    happens in GoTrue's transaction with no app session to join. Attribution is the emitter's to get
    right — a durable consumer
    legitimately records a fact for an actor that isn't its session's identity — so the function
    trusts the supplied ``user_id`` rather than re-checking it. The tailer's dispatch (admin
    session) and every read are unchanged.

    ``id`` is a UUIDv7 (via ``UUIDPk``): time-ordered, so it stays the monotonic cursor the tailer
    claims/scans on and the newest-first feeds order by — no bigint sequence."""

    __tablename__ = "business_events"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )
    # An event names itself in two halves: the app it belongs to and the verb it performs. They are
    # what a writer supplies; ``kind`` is their view — generated in the DB (see the migration), so
    # it is read-only here and no writer can make the whole disagree with its parts.
    app_name: Mapped[str]
    verb: Mapped[str]
    kind: Mapped[str] = mapped_column(
        Computed("app_name || '.' || verb", persisted=True), nullable=False
    )
    icon: Mapped[str] = mapped_column(default="circle")
    # Each correlation key is paired with the readable name it had *then*: the trail outlives its
    # subjects (a closed account, a deleted or renamed org) and RLS hides a co-member's handle at
    # read time. Every name is nullable — a system fact has no actor, a server-wide one no org, a
    # pure-id subject no name, and work outside a request no request.
    user_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    user_name: Mapped[str | None] = mapped_column(default=None)
    org_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    org_name: Mapped[str | None] = mapped_column(default=None)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    entity_name: Mapped[str | None] = mapped_column(default=None)
    request_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    # "GET /profile" — the request's own readable name, bound at request time. Without it the id
    # is only resolvable while the firehose still holds that request's lines; the firehose is a
    # recent window of files, so past its retention the id would be opaque for good.
    request_name: Mapped[str | None] = mapped_column(default=None)
    ip: Mapped[str | None] = mapped_column(default=None)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
