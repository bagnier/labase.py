from datetime import datetime, timezone, UTC


def now() -> datetime:
    return datetime.now(UTC)
