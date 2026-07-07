"""The single source of time — never call ``datetime.now()`` directly (README: one clock)."""

from datetime import UTC, datetime


def now() -> datetime:
    return datetime.now(UTC)
