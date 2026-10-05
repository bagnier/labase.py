"""The single source of time — never call ``datetime.now()`` directly (AGENTS: a single clock)."""

from datetime import UTC, datetime


def now() -> datetime:
    return datetime.now(UTC)


def ago(ts: datetime, now: datetime) -> str:
    """``3h ago``, or ``Mar 4`` past a week."""
    secs = max(0.0, (now - ts).total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    if secs < 604800:
        return f"{int(secs // 86400)}d ago"
    return ts.strftime("%b %-d")
