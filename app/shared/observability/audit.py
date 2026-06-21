import json
from typing import Any

import structlog
from fastapi import BackgroundTasks
from sqlalchemy import text

from app.shared.persistence.database import admin_session_factory

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
                    "INSERT INTO public.audit_logs (level, event, user_id, ip, payload) "
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
        log.warning("audit.write_failed", event=event, user_id=user_id)


def record_audit_event(
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
