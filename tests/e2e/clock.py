"""Programmatic test clock.

Holds a frozen instant (``_frozen``) and exposes its ``now()`` to be monkeypatched
over ``app.shared.clock.now`` for the duration of a test (see tests.plugin). Both
drivers run the app in-process, so that single patch reaches every clock.now()
call — no file, no cross-process mechanism, no test seam in production code. Steps
drive the frozen instant through set_current_date / advance_days / ensure / reset.
"""

from datetime import UTC, date, datetime, timedelta

_frozen: datetime | None = None


def now() -> datetime:
    """Patched over app.shared.clock.now during tests (see tests.plugin)."""
    return _frozen if _frozen is not None else datetime.now(UTC)


def set_current_date(value: str) -> None:
    global _frozen
    _frozen = datetime.fromisoformat(value).replace(tzinfo=UTC)


def advance_days(days: int) -> None:
    global _frozen
    _frozen = (_frozen or datetime.now(UTC)) + timedelta(days=days)


def ensure(default_iso: str) -> None:
    """Pin a deterministic instant if no scenario step has set one yet."""
    if _frozen is None:
        set_current_date(default_iso)


def reset() -> None:
    global _frozen
    _frozen = None


def today() -> date:
    return now().date()
