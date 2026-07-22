"""Driver-agnostic seeding for the unified-logs scenarios.

Two of the three sources are seeded through their real writers:
- request lines → the firehose's own writer (``append_firehose``);
- business events → the shared ``BusinessEventLog`` model.

Issue occurrences are the exception. The production path — emitting ``ExceptionCaptured`` —
records through the app's *shared* engine (``admin_session_factory``), which asyncpg can't be
driven from the browser driver's seed thread while the app is live (cross-loop corruption). So
issues are written directly through the driver's own session; because the ``error_*`` tables are
private to the issues context (the import-linter contract forbids importing its models), this is
the one place a raw insert is warranted — it also lets a fixture backdate ``created_at`` freely.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text

from apps.shared import clock
from apps.shared.events.store import BusinessEventLog

# Deterministic ids so a seed step and a filter step agree on "Acme" / "alice@…" without needing
# a real org/user row (the timeline filters by the raw id it stored).
_NS = uuid.UUID("00000000-0000-0000-0000-00000000da7a")


def logs_org_id(name: str) -> str:
    return str(uuid.uuid5(_NS, f"org:{name}"))


def logs_user_id(email: str) -> str:
    return str(uuid.uuid5(_NS, f"user:{email}"))


def _uuid(value: str | None) -> uuid.UUID | None:
    return uuid.UUID(value) if value else None


def event_model(
    event: str,
    *,
    org: str | None = None,
    user: str | None = None,
    level: str = "info",
    when: datetime | None = None,
    request_id: str | None = None,
) -> BusinessEventLog:
    """A ready-to-``add`` business-event row — the same model the persister writes, with an
    explicit ``created_at`` so a fixture can predate the current day (the writer can't backdate)."""
    return BusinessEventLog(
        created_at=when or clock.now(),
        level=level,
        kind=event,
        user_id=_uuid(user),
        org_id=_uuid(org),
        request_id=request_id,
    )


def firehose_record(
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


# Issue occurrences: a group (by fingerprint) plus one event carrying the correlation context.
INSERT_ERROR_GROUP = text(
    "INSERT INTO error_groups (fingerprint, title, first_seen, last_seen) "
    "VALUES (:fp, :title, :ts, :ts) RETURNING id"
)
INSERT_ERROR_EVENT = text(
    "INSERT INTO error_events (group_id, created_at, context) "
    "VALUES (:gid, :ts, CAST(:context AS jsonb))"
)


def group_params(title: str, when: datetime | None = None) -> dict[str, Any]:
    return {"fp": f"{title}:{uuid.uuid4()}", "title": title, "ts": when or clock.now()}
