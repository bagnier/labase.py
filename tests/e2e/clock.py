"""Programmatic test clock, fully independent of the drivers.

Both run modes run the app under our control — in-process (API) or as a
subprocess we spawn with our environment (browser) — so one cross-process
mechanism pins "now": write the frozen instant to a file that
app.shared.clock.now() reads (path in LABASE_CLOCK_FILE, inherited by the
subprocess). The file is the single source of truth, so these are stateless
functions: no instance to own or pass around, no coupling to a driver.
"""

import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path


def _path() -> Path:
    return Path(os.environ["LABASE_CLOCK_FILE"])


def _read() -> datetime | None:
    try:
        raw = _path().read_text().strip()
    except FileNotFoundError:
        return None
    return datetime.fromisoformat(raw) if raw else None


def _write(value: datetime | None) -> None:
    _path().write_text(value.isoformat() if value else "")


def set_current_date(value: str) -> None:
    _write(datetime.fromisoformat(value).replace(tzinfo=UTC))


def advance_days(days: int) -> None:
    _write((_read() or datetime.now(UTC)) + timedelta(days=days))


def ensure(default_iso: str) -> None:
    """Pin a deterministic instant if no scenario step has set one yet."""
    if _read() is None:
        set_current_date(default_iso)


def reset() -> None:
    _write(None)


def today() -> date:
    return (_read() or datetime.now(UTC)).date()
