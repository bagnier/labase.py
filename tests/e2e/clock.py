"""The test clock: a frozen instant patched over ``apps.shared.clock.now`` (see tests.plugin),
which reaches the app since both drivers run it in-process.
"""

from datetime import UTC, date, datetime, timedelta

_frozen: datetime | None = None


def now() -> datetime:
    return _frozen if _frozen is not None else datetime.now(UTC)


def set_current_date(value: str) -> None:
    global _frozen
    _frozen = datetime.fromisoformat(value).replace(tzinfo=UTC)


def advance_days(days: int) -> None:
    global _frozen
    _frozen = (_frozen or datetime.now(UTC)) + timedelta(days=days)


def ensure(default_iso: str) -> None:
    """Pin an instant unless a step already did."""
    if _frozen is None:
        set_current_date(default_iso)


def reset() -> None:
    global _frozen
    _frozen = None


def today() -> date:
    return now().date()
