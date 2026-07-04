import json
import uuid
from typing import Any

import structlog
from fastapi import BackgroundTasks
from sqlalchemy import text

from apps.shared.persistence.database import admin_session_factory

log = structlog.get_logger("labase.audit")


async def _insert_audit_log(
    level: str,
    event: str,
    user_id: str | None,
    ip: str | None,
    payload: dict[str, Any],
) -> None:

    try:
        async with admin_session_factory()() as session:
            await session.execute(
                text(
                    "INSERT INTO audit_logs (level, event, user_id, ip, payload) "
                    "VALUES (:level, :event, CAST(:user_id AS uuid), :ip, CAST(:payload AS jsonb))"
                ),
                {
                    "level": level,
                    "event": event,
                    "user_id": user_id,
                    "ip": ip,
                    "payload": json.dumps(payload) if payload else None,
                },
            )
            await session.commit()
    except Exception:
        log.exception("audit.write_failed", event=event, user_id=user_id)


def _record_audit_event(
    bg: BackgroundTasks,
    *,
    level: str,
    event: str,
    user_id: str | None = None,
    ip: str | None = None,
    **payload: Any,
) -> None:
    log.info(event, level=level, user_id=user_id, ip=ip, **payload)
    bg.add_task(_insert_audit_log, level, event, user_id, ip, payload)


def audit(
    bg: BackgroundTasks,
    event: str,
    *,
    level: str = "info",
    user_id: str | uuid.UUID | None = None,
    org_id: str | uuid.UUID | None = None,
    ip: str | None = None,
    **fields: Any,
) -> None:
    if org_id is not None:
        fields = {"org_id": str(org_id), **fields}
    _record_audit_event(
        bg,
        level=level,
        event=event,
        user_id=str(user_id) if user_id is not None else None,
        ip=ip,
        **fields,
    )
