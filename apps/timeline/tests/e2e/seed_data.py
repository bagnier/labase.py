"""Seeding for the timeline scenarios, on either driver. Log lines and facts go through their real
models; occurrences are raw inserts on the driver's session, since the capture path's shared engine
cannot be driven from the browser driver's seed thread, and the issues models are private.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text

from apps.shared import clock
from apps.shared.events.models import BusinessEventRecord

# Stable ids, so seed and filter steps agree on "Acme" without a real row.
_NS = uuid.UUID("00000000-0000-0000-0000-00000000da7a")

# The request tracer's logger name, not exported by production.
_REQUEST_LOGGER = "apps.shared.logs.request"


def timeline_org_id(name: str) -> str:
    return str(uuid.uuid5(_NS, f"org:{name}"))


def timeline_user_id(email: str) -> str:
    return str(uuid.uuid5(_NS, f"user:{email}"))


def timeline_request_id(token: str) -> str:
    """``"r-100"`` → a stable uuid5, so the Gherkin stays plain."""
    return str(uuid.uuid5(_NS, f"request:{token}"))


def _uuid(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


def event_model(
    event: str,
    *,
    org: str | None = None,
    user: str | None = None,
    when: datetime | None = None,
    request_id: str | None = None,
    request_name: str | None = None,
    entity_name: str | None = None,
) -> BusinessEventRecord:
    """A fact to ``add``, with a ``created_at`` a fixture may backdate; ``kind`` such as
    ``"todo.created"`` is split into its two columns."""
    app_name, _, verb = event.partition(".")
    return BusinessEventRecord(
        created_at=when or clock.now(),
        app_name=app_name,
        verb=verb,
        user_id=_uuid(user),
        org_id=_uuid(org),
        request_id=_uuid(request_id),
        request_name=request_name,
        entity_id=uuid.uuid7() if entity_name else None,
        entity_name=entity_name,
    )


def event_run(count: int, org: str, *, now: datetime) -> list[BusinessEventRecord]:
    """``count`` facts a minute apart, oldest first: the journal pages on the insert-minted id,
    so backdated rows must be inserted in time order. Each has its own ``entity_name`` for paging
    assertions."""
    return [
        event_model(
            "todo.created",
            org=org,
            when=now - timedelta(minutes=i),
            entity_name=f"fact {i:03d}",
        )
        for i in reversed(range(count))
    ]


def log_line(
    event: str,
    *,
    org: str | None = None,
    user: str | None = None,
    level: str = "info",
    when: datetime | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "timestamp": (when or clock.now()).isoformat(),
        "level": level,
        "logger": _REQUEST_LOGGER,
        "event": event,
        "org_id": org,
        "user_id": user,
        "request_id": request_id,
    }


def error_context(
    *, org: str | None = None, user: str | None = None, request_id: str | None = None
) -> dict[str, str]:
    return {
        k: v
        for k, v in {"org_id": org, "user_id": user, "request_id": request_id}.items()
        if v is not None
    }


INSERT_ISSUE = text(
    "INSERT INTO issues (fingerprint, title, first_seen, last_seen) "
    "VALUES (:fp, :title, :ts, :ts) RETURNING id"
)
INSERT_OCCURRENCE = text(
    "INSERT INTO issue_occurrences (issue_id, created_at, context) "
    "VALUES (:iid, :ts, CAST(:context AS jsonb))"
)


def issue_params(title: str, when: datetime | None = None) -> dict[str, Any]:
    return {"fp": f"{title}:{uuid.uuid7()}", "title": title, "ts": when or clock.now()}
